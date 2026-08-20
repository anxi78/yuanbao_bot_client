"""
词库引擎（lexicon engine）

参照 Secluded 词库格式实现的轻量版词库系统，供元宝 Bot 使用。

支持的格式（v1：核心 + 条件语句）：
  - 指令行 / 回复行 配对，自上而下逐行解析。
  - **空行作为规则之间的分隔符**（一条规则到空行结束）。
  - `//` 开头的行视为注释，跳过；行内 `//` 仅当其前面是空白时才视为注释
    起点（以避免误伤 URL 中的 `https://`、`http://` 等）。
  - 装饰性分隔行（仅由 —-=*· 等符号组成）跳过，避免误判为指令。
  - 触发匹配：
      * 触发为 `.*`           -> 匹配任意消息（应放在词库末尾）。
      * 触发含 ( ) [ ] .* |   -> 按正则 re.fullmatch 匹配；
                                   `(.*)` 捕获组 -> `%括号1%`、`%括号2%` …
      * 否则                  -> 精确相等匹配。
  - 变量（回复与条件中均可使用）：
      `%QQ%`→发送者ID  `%群号%`→群号  `%昵称%`→发送者昵称
      `%Account%`→bot_id  `%括号N%`→第 N 个捕获组
  - 条件语句（回复块内）：
      `如果:` / `if:` 开始，`如果尾` 结束，`返回` 提前结束。
      条件形如 `%var% OP 值`，OP ∈ == != >= <= > <；多条件用 & (且) / | (或) 连接。
      命中且有 `返回` -> 只执行真分支；无 `返回` -> 真分支与否则分支都执行。
      不支持的 `$函数$` 按 False 处理（v1 限制）。

注意：条件规则若没有 else 且紧跟另一条以纯文本开头的规则，可能会把下一条指令误吞为
else。常规写法（有 else 文本、或以 `.*` 结尾、或规则间用注释分隔）不受影响。
"""

import os
import re
import asyncio
import logging
import requests

logger = logging.getLogger("yuanbao_bot")

# 装饰性分隔行（仅这些符号组成）直接跳过
_DECORATIVE_RE = re.compile(r"^[\-\—\=\*\·\━\~\s]+$")

# 触发里出现这些符号时，按正则 fullmatch 处理
_REGEX_HINT_RE = re.compile(r"[().*\[\]|]")

# 词库内 HTTP 请求语法：$访问 <url>$  (GET)  /  $访问 POST <url> <body>$  (POST)
_ACCESS_RE = re.compile(r"\$访问\s+([^$]*)\$")

# 词库内图片发送语法：
#   网络图片：$图片 <http(s) URL>$         （URL 中可用 %QQ% %群号% 等变量）
#   本地图片：$图片 <本地路径>$             （相对/绝对路径，如 路径/文件名.png）
# 同一个 $图片 ...$ 标记既可表示网络图片（以 http:// / https:// 开头），
# 也可表示本地图片（其余情况），由调用方下载/校验后作为图片消息发送。
_IMAGE_RE = re.compile(r"\$图片\s+([^$]*)\$")

# 变量赋值：整行形如 `变量名:$访问 ...$` 或 `变量名:$图片 ...$` 时，
# 把该请求结果存入变量（ctx[变量名]），且不输出该行。
# 变量名后必须紧跟冒号再紧跟 $ 标记（中间无空格）才视为赋值；加空格则按普通内联处理。
# 同一回复内后续的 %变量名% 均可引用该值（包含 $图片 的 URL 内）。
_TOKEN_RE = re.compile(r"\$(访问|图片)\s+([^$]*)\$")
_ASSIGN_LINE_RE = re.compile(r"^([A-Za-z_]\w*):(\$(?:访问|图片)\s+[^$]*\$)\s*$")


class LexiconEngine:
    def __init__(self, folder: str, enabled: bool = True):
        self.folder = folder
        self.enabled = enabled
        self.rules = []  # list of (trigger:str, reply_lines:list[str])
        self.files_loaded = 0
        self.rules_loaded = 0

    # ------------------------------------------------------------------ #
    # 加载
    # ------------------------------------------------------------------ #
    def load(self) -> dict:
        """递归扫描 folder 下所有 .txt 文件并解析为规则。返回统计信息。"""
        self.rules = []
        self.files_loaded = 0
        if not os.path.isdir(self.folder):
            logger.warning("词库目录不存在: %s（已自动创建）", self.folder)
            try:
                os.makedirs(self.folder, exist_ok=True)
            except Exception as e:
                logger.error("创建词库目录失败: %s", e)
            self.rules_loaded = 0
            return self.stats()
        for root, _dirs, files in os.walk(self.folder):
            # 按文件名排序，保证加载顺序稳定
            for name in sorted(files):
                if not name.lower().endswith(".txt"):
                    continue
                path = os.path.join(root, name)
                try:
                    file_rules = self.parse_file(path)
                    self.rules.extend(file_rules)
                    self.files_loaded += 1
                    logger.info("词库已加载: %s（%d 条规则）", path, len(file_rules))
                except Exception as e:
                    logger.error("词库解析失败，已跳过: %s -> %s", path, e)
        self.rules_loaded = len(self.rules)
        return self.stats()

    def stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "folder": self.folder,
            "files": self.files_loaded,
            "rules": self.rules_loaded,
        }

    # ------------------------------------------------------------------ #
    # 解析
    # ------------------------------------------------------------------ #
    def parse_file(self, path: str):
        """把单个 .txt 词库文件解析为规则列表 [(trigger, reply_lines), ...]。

        约定：
          - 空行作为规则之间的分隔符（一条规则到空行结束）。
          - `//` 注释行跳过；装饰性行跳过。
          - 回复块内的多行文本会拼接为同一条回复（Secluded 忽略换行，
            仅 `\\r` / `\\n` 产生真实换行）。
        """
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        lines = raw.split("\n")
        rules = []
        n = len(lines)
        i = 0
        while i < n:
            line = self._strip_inline_comment(lines[i])
            s = line.strip()
            if not s or s.startswith("//") or _DECORATIVE_RE.match(s):
                i += 1
                continue
            # 该行是触发指令
            trigger = s
            i += 1
            reply_lines = []
            while i < n:
                cur = self._strip_inline_comment(lines[i])
                sc = cur.strip()
                if _DECORATIVE_RE.match(sc):
                    i += 1
                    continue
                if sc.startswith("//"):
                    # 纯注释行：跳过，不结束规则
                    i += 1
                    continue
                if sc == "":
                    # 空行：结束当前规则
                    i += 1
                    break
                reply_lines.append(cur)
                i += 1
            if reply_lines:
                rules.append((trigger, reply_lines))
        return rules

    @staticmethod
    def _strip_inline_comment(line: str) -> str:
        """剥离行内注释。

        仅当 `//` 位于行首，或其前面是空白字符时，才视为注释起点并截断其后内容。
        这样可避免误伤 URL 中的 `https://`、`http://` 等（其 `//` 前面是 `:`）。
        """
        idx = line.find("//")
        while idx != -1:
            if idx == 0 or line[idx - 1] in " \t":
                return line[:idx]
            idx = line.find("//", idx + 1)
        return line

    # ------------------------------------------------------------------ #
    # 匹配
    # ------------------------------------------------------------------ #
    def match(self, text: str, ctx: dict) -> str:
        """
        用 text 匹配词库规则。
        返回最终回复文本（可能为空字符串）；无任何规则命中 / 命中但无输出时返回 None。
        """
        text = text or ""
        for trigger, reply_lines in self.rules:
            m = self._match_trigger(trigger, text)
            if m is None:
                continue
            new_ctx = dict(ctx)
            for idx, val in enumerate(m.groups(), start=1):
                new_ctx["括号%d" % idx] = val if val is not None else ""
            out = self.exec_block(reply_lines, 0, len(reply_lines), new_ctx)
            if out:
                # 用换行拼接，保留行结构（词库赋值语法依赖整行判断）
                return "\n".join(out)
            # 命中但输出为空 -> 视为静默，不再回退到其他规则（首条命中即生效）
            return None
        return None

    def _match_trigger(self, trigger: str, text: str):
        t = trigger.strip()
        if t == ".*":
            return re.fullmatch(".*", text, re.DOTALL)
        if _REGEX_HINT_RE.search(t):
            try:
                return re.fullmatch(t, text, re.DOTALL)
            except re.error:
                return re.fullmatch(re.escape(t), text, re.DOTALL) if t == text else None
        # 精确匹配
        return re.fullmatch(re.escape(t), text) if t == text else None

    # ------------------------------------------------------------------ #
    # 回复块解释器（处理 如果/如果尾/返回）
    # ------------------------------------------------------------------ #
    def exec_block(self, lines, start, end, ctx) -> list:
        out = []
        i = start
        while i < end:
            s = lines[i].strip()
            if s.startswith("如果:") or s.startswith("if:"):
                cond = s.split(":", 1)[1].strip()
                depth = 1
                j = i + 1
                true_end = None
                tail = None
                while j < end:
                    sj = lines[j].strip()
                    if sj.startswith("如果:") or sj.startswith("if:"):
                        depth += 1
                    elif sj == "如果尾":
                        depth -= 1
                        if depth == 0:
                            tail = j
                            if true_end is None:
                                true_end = j
                            break
                    elif sj == "返回" and depth == 1:
                        true_end = j
                    j += 1
                if tail is None:
                    tail = end
                if self.eval_condition(cond, ctx):
                    out.extend(self.exec_block(lines, i + 1, true_end, ctx))
                    if true_end != tail:
                        # 有 返回 -> 直接结束，跳过 else
                        break
                    else:
                        # 无 返回 -> 真分支与否则分支都执行
                        out.extend(self.exec_block(lines, tail + 1, end, ctx))
                        break
                else:
                    out.extend(self.exec_block(lines, tail + 1, end, ctx))
                    break
            elif s == "返回":
                break
            elif s == "如果尾":
                i += 1
            else:
                out.append(self.substitute(lines[i], ctx))
                i += 1
        return out

    # ------------------------------------------------------------------ #
    # 条件求值
    # ------------------------------------------------------------------ #
    def eval_condition(self, cond: str, ctx: dict) -> bool:
        cond = (cond or "").strip()
        if not cond:
            return True
        if "$" in cond:
            logger.debug("词库条件含不支持的 $函数$，按 False 处理: %r", cond)
            return False
        for or_part in re.split(r"\|", cond):
            ok = True
            for atom in re.split(r"&", or_part):
                if not self._eval_atom(atom, ctx):
                    ok = False
                    break
            if ok:
                return True
        return False

    def _eval_atom(self, atom: str, ctx: dict) -> bool:
        atom = atom.strip()
        if not atom:
            return True
        m = re.search(r"(>=|<=|==|!=|>|<)", atom)
        if not m:
            return False
        op = m.group(1)
        lhs = self._resolve(atom[: m.start()].strip(), ctx)
        rhs = self._resolve(atom[m.end():].strip(), ctx)
        if rhs == ".*":
            return bool(str(lhs))
        return self._cmp(op, str(lhs), str(rhs))

    @staticmethod
    def _resolve(token: str, ctx: dict):
        token = token.strip()
        if len(token) > 2 and token.startswith("%") and token.endswith("%"):
            return ctx.get(token[1:-1], "")
        return token

    @staticmethod
    def _cmp(op: str, a: str, b: str) -> bool:
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        try:
            fa, fb = float(a), float(b)
            a, b = fa, fb
        except (ValueError, TypeError):
            pass
        if op == ">=":
            return a >= b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        if op == "<":
            return a < b
        return False

    # ------------------------------------------------------------------ #
    # 变量替换
    # ------------------------------------------------------------------ #
    def substitute(self, text: str, ctx: dict) -> str:
        def repl(m):
            name = m.group(1)
            return str(ctx.get(name, m.group(0)))

        text = re.sub(r"%([^%]+)%", repl, text)
        text = text.replace("\\r", "\n").replace("\\n", "\n")
        return text

    # ------------------------------------------------------------------ #
    # HTTP 请求（$访问 ...$）
    # ------------------------------------------------------------------ #
    def fetch_url(self, spec: str, ctx: dict) -> str:
        """执行一条 $访问 ...$ 请求，返回响应文本（失败返回空串）。

        语法：
          $访问 <url>$                 -> GET
          $访问 POST <url> <body>$     -> POST（body 为 url 之后的全部内容）
        spec 中的 %变量% 在调用前已由 substitute 解析完毕。
        """
        s = spec.strip()
        method = "GET"
        body = None
        m = re.match(r"^POST\s+(\S+)\s*(.*)$", s, re.DOTALL)
        if m:
            method = "POST"
            url = m.group(1).strip()
            body = m.group(2).strip() or None
        else:
            url = s
        try:
            if method == "POST":
                resp = requests.post(
                    url, data=body,
                    headers={"Content-Type": "text/plain"},
                    timeout=10,
                )
            else:
                resp = requests.get(url, timeout=10)
            enc = resp.apparent_encoding or resp.encoding
            if enc:
                resp.encoding = enc
            return resp.text
        except Exception as e:
            logger.error("词库 API 请求失败 (%s %s): %s", method, url, e)
            return ""

    async def resolve_requests(self, text: str, ctx: dict) -> str:
        """扫描文本中的 $访问 ...$ 标记，在线程池执行请求后替换回响应文本。"""
        matches = list(_ACCESS_RE.finditer(text))
        if not matches:
            return text
        loop = asyncio.get_running_loop()
        results = []
        for m in matches:
            try:
                res = await loop.run_in_executor(None, self.fetch_url, m.group(1), ctx)
            except Exception as e:
                logger.error("词库 API 解析失败: %s", e)
                res = ""
            results.append((m.start(), m.end(), res))
        out = text
        for start, end, res in reversed(results):
            out = out[:start] + res + out[end:]
        return out

    def extract_images(self, text: str):
        """扫描文本中的 $图片 ...$ 标记，将其与正文分离。

        返回 (cleaned_text, image_specs)：
          - cleaned_text : 移除所有 $图片 ...$ 后的纯文本（用于普通消息发送）
          - image_specs  : 列表，元素为 $图片 ...$ 内部原始字符串（已做过 %变量% 替换）。
                           调用方据此判断：
                             * 以 http:// 或 https:// 开头 -> 网络图片（需下载）
                             * 否则                      -> 本地图片（需校验路径）

        URL 中的 %QQ% 等变量在 exec_block 的 substitute 阶段已替换完毕。
        """
        specs = [m.group(1).strip() for m in _IMAGE_RE.finditer(text)]
        cleaned = _IMAGE_RE.sub("", text)
        return cleaned, specs

    # ------------------------------------------------------------------ #
    # 综合解析（$访问$ / $图片$ / 变量赋值），按出现顺序执行
    # ------------------------------------------------------------------ #
    @staticmethod
    def _substitute_vars(text: str, ctx: dict) -> str:
        """仅做 %变量% 替换（不做 \\r\\n 转换），用于 URL / 请求体 / 结果合并。"""

        def repl(mm):
            return str(ctx.get(mm.group(1), mm.group(0)))

        return re.sub(r"%([^%]+)%", repl, text)

    async def resolve(self, text: str, ctx: dict):
        """统一处理回复中的 $访问 ...$ 与 $图片 ...$ 标记，并返回 (text, image_specs)。

        相比分别调用 resolve_requests + extract_images，本方法额外支持：
          * 变量赋值：整行形如 `变量名:$访问 ...$` / `变量名:$图片 ...$` 时，
            把该请求结果存入 ctx[变量名]，且不输出该行文本（用于链式调用）。
          * 同一回复内后续的 %变量名% 均可引用（含 $图片 URL 内）。

        处理顺序为从左到右，因此后出现的标记可以使用先赋值的变量。
        """
        loop = asyncio.get_running_loop()
        output = []
        image_specs = []
        last = 0
        for m in _TOKEN_RE.finditer(text):
            start, end = m.start(), m.end()
            kind = m.group(1)
            inner = self._substitute_vars(m.group(2).strip(), ctx)

            # 判断该 token 所在整行是否为「变量名:$TOKEN$」赋值
            line_start = text.rfind("\n", 0, start) + 1
            line_end = text.find("\n", end)
            if line_end == -1:
                line_end = len(text)
            assign = _ASSIGN_LINE_RE.match(text[line_start:line_end].strip())

            if assign:
                # 跳过「变量名:」与整个 $TOKEN$，仅输出其之前的内容
                name_start = start - len(assign.group(1)) - 1  # 退过 : 与变量名
                output.append(text[last:name_start])
                last = end
                if kind == "访问":
                    res = await loop.run_in_executor(None, self.fetch_url, inner, ctx)
                    ctx[assign.group(1)] = res if res is not None else ""
                else:
                    ctx[assign.group(1)] = inner
                    image_specs.append(inner)
            else:
                output.append(text[last:start])
                last = end
                if kind == "访问":
                    res = await loop.run_in_executor(None, self.fetch_url, inner, ctx)
                    output.append(res if res is not None else "")
                else:
                    image_specs.append(inner)

        output.append(text[last:])
        cleaned = "".join(output)
        # 最终再替换一次：处理普通文本中引用了已赋值变量的情况
        cleaned = self._substitute_vars(cleaned, ctx)
        image_specs = [self._substitute_vars(s, ctx) for s in image_specs]
        return cleaned, image_specs


if __name__ == "__main__":
    import tempfile
    import shutil

    d = tempfile.mkdtemp(prefix="lex_", dir=os.path.expanduser("~"))
    try:
        eng = LexiconEngine(d, enabled=True)
        sample = """\
// 测试词库
你好
你好，我是机器人\\r
亲爱的！

(.*)天气
%括号1%的天气是晴天

查我的信息
如果:%QQ%==123456
你的QQ是123456
返回
如果尾
你不是VIP

(.*)
你说了: %括号1%
"""
        p = os.path.join(d, "t.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(sample)
        eng.load()
        assert eng.rules_loaded == 4, eng.rules_loaded
        ctx = {"QQ": "999", "群号": "g1", "昵称": "张三", "Account": "bot"}
        r1 = eng.match("你好", ctx)
        assert "你好，我是机器人" in r1 and "亲爱的！" in r1, r1
        r2 = eng.match("北京天气", ctx)
        assert "北京" in r2 and "晴天" in r2, r2
        r3 = eng.match("查我的信息", ctx)
        assert "不是VIP" in r3, r3
        r4 = eng.match("随便说点什么", ctx)
        assert "你说了: 随便说点什么" in r4, r4
        ctx_vip = dict(ctx)
        ctx_vip["QQ"] = "123456"
        r5 = eng.match("查我的信息", ctx_vip)
        assert "你的QQ是123456" in r5, r5

        # 离线测试 $访问 ...$ 的 GET/POST 解析与替换（用 mock 替代网络）
        class _FakeResp:
            text = ""
            encoding = "utf-8"
            apparent_encoding = "utf-8"

        class _FakeReq:
            def get(self, url, timeout=None):
                r = _FakeResp()
                r.text = "GET:" + url
                return r

            def post(self, url, data=None, headers=None, timeout=None):
                r = _FakeResp()
                r.text = "POST:" + url + ":" + str(data)
                return r

        globals()["requests"] = _FakeReq()
        out_get = asyncio.run(eng.resolve_requests("结果:$访问 https://x.com/a$", ctx))
        assert "GET:https://x.com/a" in out_get, out_get
        out_post = asyncio.run(
            eng.resolve_requests("结果:$访问 POST https://x.com/p hello body$", ctx)
        )
        assert "POST:https://x.com/p:hello body" in out_post, out_post
        print("词库请求自测通过")

        # 离线测试变量赋值：a:$访问 ...$ 把结果存入 %a%，后续 %a% 可引用
        ctx2 = dict(ctx)
        text, imgs = asyncio.run(
            eng.resolve(
                "a:$访问 https://api.ai/x?q=%括号1%$\n$图片 https://img/x?t=%a%$",
                ctx2,
            )
        )
        assert ctx2.get("a") == "GET:https://api.ai/x?q=%括号1%", ctx2.get("a")
        assert "%a%" not in text, text
        assert imgs and "t=GET:https://api.ai/x?q=%括号1%" in imgs[0], imgs
        # 非赋值（有空格）应内联替换
        text2, imgs2 = asyncio.run(
            eng.resolve("前缀: $访问 https://x.com/b$", ctx)
        )
        assert "前缀: GET:https://x.com/b" in text2, text2
        print("词库变量赋值自测通过")
        print("词库自测通过：", eng.stats())
    finally:
        shutil.rmtree(d, ignore_errors=True)
