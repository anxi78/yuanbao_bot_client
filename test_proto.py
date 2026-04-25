#!/usr/bin/env python3
"""测试手动 protobuf 编解码是否与官方库一致 - 简化版"""

import sys
sys.path.insert(0, '/data/data/com.termux/files/home/yuanbao_bot_client')
from spam_sender import SimpleProtobufCodec

from google.protobuf import descriptor_pb2, descriptor, symbol_database, message_factory, descriptor_pool

pool = descriptor_pool.Default()

# ===== 注册 conn.proto 消息类型 =====
conn_fd = descriptor_pb2.FileDescriptorProto()
conn_fd.name = 'conn_test.proto'
conn_fd.package = 'trpc.yuanbao.conn_common'
conn_fd.syntax = 'proto3'

head_msg = conn_fd.message_type.add()
head_msg.name = 'Head'
fields = [
    ('cmdType', 1, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32),
    ('cmd', 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
    ('seqNo', 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32),
    ('msgId', 4, descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
    ('module', 5, descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
    ('status', 10, descriptor_pb2.FieldDescriptorProto.TYPE_INT32),
]
for name, num, typ in fields:
    f = head_msg.field.add()
    f.name = name
    f.number = num
    f.type = typ
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

conn_msg = conn_fd.message_type.add()
conn_msg.name = 'ConnMsg'
f = conn_msg.field.add()
f.name = 'head'
f.number = 1
f.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
f.type_name = '.trpc.yuanbao.conn_common.Head'
f = conn_msg.field.add()
f.name = 'data'
f.number = 2
f.type = descriptor_pb2.FieldDescriptorProto.TYPE_BYTES
f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

pool.Add(conn_fd)

# 获取消息描述符
head_desc = pool.FindMessageTypeByName('trpc.yuanbao.conn_common.Head')
conn_desc = pool.FindMessageTypeByName('trpc.yuanbao.conn_common.ConnMsg')

# 创建动态消息类
HeadProto = message_factory.GetMessageClass(head_desc)
ConnMsgProto = message_factory.GetMessageClass(conn_desc)

# ===== 注册 biz.proto 消息类型 =====
biz_fd = descriptor_pb2.FileDescriptorProto()
biz_fd.name = 'biz_test.proto'
biz_fd.package = 'trpc.yuanbao.biz'
biz_fd.syntax = 'proto3'

# Member
member_msg = biz_fd.message_type.add()
member_msg.name = 'Member'
for name, num, typ in [
    ('userId', 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
    ('nickName', 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
    ('userType', 3, descriptor_pb2.FieldDescriptorProto.TYPE_INT32),
]:
    f = member_msg.field.add()
    f.name = name
    f.number = num
    f.type = typ
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

# GetGroupMemberListReq
req_msg = biz_fd.message_type.add()
req_msg.name = 'GetGroupMemberListReq'
f = req_msg.field.add()
f.name = 'groupCode'
f.number = 1
f.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

# GetGroupMemberListRsp
rsp_msg = biz_fd.message_type.add()
rsp_msg.name = 'GetGroupMemberListRsp'
for name, num, typ in [
    ('code', 1, descriptor_pb2.FieldDescriptorProto.TYPE_INT32),
    ('message', 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
]:
    f = rsp_msg.field.add()
    f.name = name
    f.number = num
    f.type = typ
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
f = rsp_msg.field.add()
f.name = 'memberList'
f.number = 3
f.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
f.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
f.type_name = '.trpc.yuanbao.biz.Member'

pool.Add(biz_fd)

MemberProto = message_factory.GetMessageClass(pool.FindMessageTypeByName('trpc.yuanbao.biz.Member'))
GetGroupMemberListReqProto = message_factory.GetMessageClass(pool.FindMessageTypeByName('trpc.yuanbao.biz.GetGroupMemberListReq'))
GetGroupMemberListRspProto = message_factory.GetMessageClass(pool.FindMessageTypeByName('trpc.yuanbao.biz.GetGroupMemberListRsp'))

# ===== 测试 1: Head 编码 =====
print("=== 测试 1: encode_head ===")
my_head = SimpleProtobufCodec.encode_head(
    cmd_type=0, cmd="test_cmd", seq_no=123,
    msg_id="test_msg_id_123", module="test_module"
)
print(f"手动编码 head ({len(my_head)} bytes): {my_head.hex()}")

head_pb = HeadProto(cmdType=0, cmd="test_cmd", seqNo=123, msgId="test_msg_id_123", module="test_module")
pb_head_bytes = head_pb.SerializeToString()
print(f"protobuf 编码 head ({len(pb_head_bytes)} bytes): {pb_head_bytes.hex()}")

if my_head == pb_head_bytes:
    print("✓ head 编码完全一致!")
else:
    print("✗ head 编码不一致!")
    for i in range(max(len(my_head), len(pb_head_bytes))):
        if i >= len(my_head):
            print(f"  位置 {i}: 手动=缺失, protobuf={pb_head_bytes[i]:02x}")
        elif i >= len(pb_head_bytes):
            print(f"  位置 {i}: 手动={my_head[i]:02x}, protobuf=缺失")
        elif my_head[i] != pb_head_bytes[i]:
            print(f"  位置 {i}: 手动={my_head[i]:02x}, protobuf={pb_head_bytes[i]:02x}")

# ===== 测试 2: ConnMsg 编码 =====
print("\n=== 测试 2: encode_conn_msg ===")
my_conn = SimpleProtobufCodec.encode_conn_msg(my_head, b'hello world')
print(f"手动编码 conn_msg ({len(my_conn)} bytes): {my_conn.hex()}")

conn_pb = ConnMsgProto(head=head_pb, data=b'hello world')
pb_conn_bytes = conn_pb.SerializeToString()
print(f"protobuf 编码 conn_msg ({len(pb_conn_bytes)} bytes): {pb_conn_bytes.hex()}")

if my_conn == pb_conn_bytes:
    print("✓ conn_msg 编码完全一致!")
else:
    print("✗ conn_msg 编码不一致!")
    for i in range(max(len(my_conn), len(pb_conn_bytes))):
        if i >= len(my_conn):
            print(f"  位置 {i}: 手动=缺失, protobuf={pb_conn_bytes[i]:02x}")
        elif i >= len(pb_conn_bytes):
            print(f"  位置 {i}: 手动={my_conn[i]:02x}, protobuf=缺失")
        elif my_conn[i] != pb_conn_bytes[i]:
            print(f"  位置 {i}: 手动={my_conn[i]:02x}, protobuf={pb_conn_bytes[i]:02x}")

# ===== 测试 3: ConnMsg 解码 =====
print("\n=== 测试 3: decode_conn_msg ===")
decoded = SimpleProtobufCodec.decode_conn_msg(pb_conn_bytes)
if decoded:
    h = decoded.get('head', {})
    d = decoded.get('data', b'')
    print(f"解码结果: cmd_type={h.get('cmd_type')}, cmd={h.get('cmd')}, msg_id={h.get('msg_id')}")
    print(f"  seq_no={h.get('seq_no')}, module={h.get('module')}, status={h.get('status')}")
    print(f"  data={d}")
    if h.get('cmd_type') == 0 and h.get('cmd') == 'test_cmd' and d == b'hello world':
        print("✓ decode_conn_msg 正确!")
    else:
        print("✗ decode_conn_msg 结果异常!")
else:
    print("✗ decode_conn_msg 返回 None!")

# ===== 测试 4: GetGroupMemberListReq 编码 =====
print("\n=== 测试 4: encode_get_group_member_list_req ===")
my_req = SimpleProtobufCodec.encode_get_group_member_list_req("123456")
print(f"手动编码 req ({len(my_req)} bytes): {my_req.hex()}")

req_pb = GetGroupMemberListReqProto(groupCode="123456")
pb_req_bytes = req_pb.SerializeToString()
print(f"protobuf 编码 req ({len(pb_req_bytes)} bytes): {pb_req_bytes.hex()}")

if my_req == pb_req_bytes:
    print("✓ GetGroupMemberListReq 编码完全一致!")
else:
    print("✗ GetGroupMemberListReq 编码不一致!")
    for i in range(max(len(my_req), len(pb_req_bytes))):
        if i >= len(my_req):
            print(f"  位置 {i}: 手动=缺失, protobuf={pb_req_bytes[i]:02x}")
        elif i >= len(pb_req_bytes):
            print(f"  位置 {i}: 手动={my_req[i]:02x}, protobuf=缺失")
        elif my_req[i] != pb_req_bytes[i]:
            print(f"  位置 {i}: 手动={my_req[i]:02x}, protobuf={pb_req_bytes[i]:02x}")

# ===== 测试 5: GetGroupMemberListRsp 解码 =====
print("\n=== 测试 5: decode_get_group_member_list_rsp ===")
rsp_pb = GetGroupMemberListRspProto()
rsp_pb.code = 0
rsp_pb.message = 'success'
m1 = rsp_pb.memberList.add()
m1.userId = 'user001'
m1.nickName = '用户1'
m1.userType = 0
m2 = rsp_pb.memberList.add()
m2.userId = 'user002'
m2.nickName = '用户2'
m2.userType = 1

pb_rsp_bytes = rsp_pb.SerializeToString()
print(f"protobuf 编码 rsp ({len(pb_rsp_bytes)} bytes): {pb_rsp_bytes.hex()}")

decoded_rsp = SimpleProtobufCodec.decode_get_group_member_list_rsp(pb_rsp_bytes)
print(f"手动解码结果: {decoded_rsp}")

if decoded_rsp.get('code') == 0 and len(decoded_rsp.get('member_list', [])) == 2:
    m = decoded_rsp['member_list'][0]
    if m.get('user_id') == 'user001' and m.get('nick_name') == '用户1' and m.get('user_type') == 0:
        print("✓ decode_get_group_member_list_rsp 解码完全正确!")
    else:
        print("✗ 成员字段解码异常")
else:
    print("✗ decode_get_group_member_list_rsp 解码异常!")

# ===== 测试 6: 模拟完整请求+响应流程 =====
print("\n=== 测试 6: 完整请求+响应流程 ===")
# 构建请求 ConnMsg
my_biz_req = SimpleProtobufCodec.encode_get_group_member_list_req("288327363")
my_req_head = SimpleProtobufCodec.encode_head(
    cmd_type=0, cmd="get_group_member_list", seq_no=1,
    msg_id="test_msg_abc123", module="yuanbao_openclaw_proxy"
)
my_req_conn = SimpleProtobufCodec.encode_conn_msg(my_req_head, my_biz_req)
print(f"请求 ConnMsg ({len(my_req_conn)} bytes)")

# 用 protobuf 构建同样的请求
req_pb2 = GetGroupMemberListReqProto(groupCode="288327363")
biz_req_bytes = req_pb2.SerializeToString()
req_head_pb = HeadProto(cmdType=0, cmd="get_group_member_list", seqNo=1, msgId="test_msg_abc123", module="yuanbao_openclaw_proxy")
req_conn_pb = ConnMsgProto(head=req_head_pb, data=biz_req_bytes)
pb_req_conn = req_conn_pb.SerializeToString()
print(f"protobuf 请求 ConnMsg ({len(pb_req_conn)} bytes)")

if my_req_conn == pb_req_conn:
    print("✓ 完整请求编码一致!")
else:
    print("✗ 完整请求编码不一致!")

# 模拟响应
rsp_pb2 = GetGroupMemberListRspProto()
rsp_pb2.code = 0
rsp_pb2.message = 'success'
m = rsp_pb2.memberList.add()
m.userId = 'u_anxi'
m.nickName = 'Anxi'
m.userType = 0

rsp_head_pb = HeadProto(cmdType=1, cmd="get_group_member_list", seqNo=1, msgId="test_msg_abc123", module="yuanbao_openclaw_proxy", status=0)
rsp_conn_pb = ConnMsgProto(head=rsp_head_pb, data=rsp_pb2.SerializeToString())
pb_rsp_conn = rsp_conn_pb.SerializeToString()
print(f"\n模拟响应 ConnMsg ({len(pb_rsp_conn)} bytes): {pb_rsp_conn.hex()}")

# 用我的 decode_conn_msg 解码响应
decoded_conn = SimpleProtobufCodec.decode_conn_msg(pb_rsp_conn)
if decoded_conn:
    h = decoded_conn.get('head', {})
    print(f"解码 head: cmd_type={h.get('cmd_type')}, cmd={h.get('cmd')}, msg_id={h.get('msg_id')}, status={h.get('status')}")
    
    biz_data = decoded_conn.get('data', b'')
    decoded_rsp2 = SimpleProtobufCodec.decode_get_group_member_list_rsp(biz_data)
    print(f"解码 rsp: code={decoded_rsp2.get('code')}, msg={decoded_rsp2.get('message')}")
    print(f"  成员列表: {decoded_rsp2.get('member_list')}")
    
    if decoded_rsp2.get('code') == 0 and len(decoded_rsp2.get('member_list', [])) == 1:
        print("✓ 完整流程解码正确!")
    else:
        print("✗ 完整流程解码异常")
else:
    print("✗ decode_conn_msg 返回 None!")

print("\n所有测试完成!")