# !/usr/bin/env python
# coding=utf-8
import platform
import struct
import ssl
import asyncio

import logbook
from logbook import critical, warning, info

import Mumble_pb2
from channels import ChannelManager
from commands import CommandManager, NewBot
from db import User, Channel, Session
from tagpro import GroupManager
from users import UserManager


logger = logbook.StderrHandler('WARNING', bubble=True)
logger.push_application()


class Protocol:
    connection_lock = asyncio.Lock()
    bots = []
    VERSION_MAJOR = 1
    VERSION_MINOR = 2
    VERSION_PATCH = 4

    VERSION_DATA = (VERSION_MAJOR << 16) | (VERSION_MINOR << 8) | VERSION_PATCH

    PREFIX_FORMAT = ">HI"
    PREFIX_LENGTH = 6

    ID_MESSAGE = [
        Mumble_pb2.Version,
        Mumble_pb2.UDPTunnel,
        Mumble_pb2.Authenticate,
        Mumble_pb2.Ping,
        Mumble_pb2.Reject,
        Mumble_pb2.ServerSync,
        Mumble_pb2.ChannelRemove,
        Mumble_pb2.ChannelState,
        Mumble_pb2.UserRemove,
        Mumble_pb2.UserState,
        Mumble_pb2.BanList,
        Mumble_pb2.TextMessage,
        Mumble_pb2.PermissionDenied,
        Mumble_pb2.ACL,
        Mumble_pb2.QueryUsers,
        Mumble_pb2.CryptSetup,
        Mumble_pb2.ContextActionModify,
        Mumble_pb2.ContextAction,
        Mumble_pb2.UserList,
        Mumble_pb2.VoiceTarget,
        Mumble_pb2.PermissionQuery,
        Mumble_pb2.CodecVersion,
        Mumble_pb2.UserStats,
        Mumble_pb2.RequestBlob,
        Mumble_pb2.ServerConfig
    ]

    MESSAGE_ID = {v: k for k, v in enumerate(ID_MESSAGE)}

    PING_REPEAT_TIME = 5

    @property
    def num_channels(self):
        return len(self.channels)


    def __init__(self, host="mumble.koalabeast.com", name="ChangeThis",
                 channel=None, user_manager=None, root=False):
        self.reader = None
        self.writer = None
        self.username = name
        self.host = host
        self.users = UserManager()
        self.channels = {}
        self.own_user = None
        self.channel = channel
        self.channel_manager = ChannelManager()
        self.command_manager = CommandManager(self, self.users)
        self.group_manager = GroupManager(self)
        self.connected = False
        self.bots.append(self)
        if root:
            self.start_bots()


    @property
    def channel_id(self):
        if self.own_user is not None:
            return self.own_user.channel_id

    def read_loop(self):
        try:
            while self.connected:
                header = yield from self.reader.readexactly(6)
                message_type, length = struct.unpack(Protocol.PREFIX_FORMAT,
                                                     header)
                if message_type not in Protocol.MESSAGE_ID.values():
                    critical("Unknown ID, exiting.")
                    self.die()
                raw_message = (yield from self.reader.readexactly(length))
                message = Protocol.ID_MESSAGE[message_type]()
                message.ParseFromString(raw_message)
                yield from self.mumble_received(message)
        finally:
            self.pinger.cancel()
            self.writer.close()
            self.bots.remove(self)
            if not self.bots:
                l = asyncio.get_event_loop()
                l.stop()


    @asyncio.coroutine
    def mumble_received(self, message):
        if isinstance(message, Mumble_pb2.Version):
            pass

        elif isinstance(message, Mumble_pb2.Reject):
            critical("Rejected")
            self.die()


        elif isinstance(message, Mumble_pb2.CodecVersion):
            pass
        elif isinstance(message, Mumble_pb2.CryptSetup):
            pass
        elif isinstance(message, Mumble_pb2.ChannelState):
            self.channel_manager.add_from_message(message)
        elif isinstance(message, Mumble_pb2.PermissionQuery):
            pass
        elif isinstance(message, Mumble_pb2.UserState):
            if self.own_user is None:
                self.own_user = self.users.from_message(message)
                u = self.own_user
                print(u)
            elif message.session and message.session == self.own_user.session:
                self.own_user.update_from_message(message)
                u = self.own_user
            else:
                try:
                    u = self.users.from_message(message)
                except NameError:
                    u = None
            if u and u is not self.own_user:
                if u.channel_id == self.own_user.channel_id:
                    yield from self.user_joined_channel(u)
        elif isinstance(message, Mumble_pb2.ServerSync):
            pass
        elif isinstance(message, Mumble_pb2.ServerConfig):
            if self.connection_lock.locked():
                self.connection_lock.release()  # We're as connected as possible.
        elif isinstance(message, Mumble_pb2.Ping):
            pass
        elif isinstance(message, Mumble_pb2.UserRemove):
            pass
        elif isinstance(message, Mumble_pb2.TextMessage):
            yield from self.handle_text_message(message)
        elif isinstance(message, Mumble_pb2.ChannelRemove):
            self.channel_manager.del_channel(message.channel_id)
        else:
            warning("Received unknown message type")
            info(message)

    @asyncio.coroutine
    def send_protobuf(self, message):
        msg_type = Protocol.MESSAGE_ID[message.__class__]
        msg_data = message.SerializeToString()
        length = len(msg_data)
        data = struct.pack(Protocol.PREFIX_FORMAT, msg_type,
                           length) + msg_data
        self.writer.write(data)

    @asyncio.coroutine
    def send_text_message(self, message, dest):
        m = Mumble_pb2.TextMessage()
        m.message = message
        if isinstance(dest, User):
            m.session.append(dest.session)
        elif isinstance(dest, Channel):
            m.channel_id.append(dest.id)
        yield from self.send_protobuf(m)

    @asyncio.coroutine
    def init_ping(self):
        while True:
            yield from asyncio.sleep(Protocol.PING_REPEAT_TIME)
            yield from self.send_protobuf(Mumble_pb2.Ping())

    @asyncio.coroutine
    def connect(self):
        info("Connecting...")
        yield from self.connection_lock
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        # sslcontext.options |= ssl.CERT_NONE
        self.reader, self.writer = (
            yield from asyncio.open_connection(self.host, 64738,
                                               server_hostname='',
                                               ssl=ssl_context))

        version = Mumble_pb2.Version()
        version.version = Protocol.VERSION_DATA
        version.release = "%d.%d.%d" % (Protocol.VERSION_MAJOR,
                                        Protocol.VERSION_MINOR,
                                        Protocol.VERSION_PATCH)
        version.os = platform.system()
        version.os_version = "Mumble %s asyncio" % version.release

        auth = Mumble_pb2.Authenticate()
        auth.username = self.username
        self.pinger = asyncio.Task(self.init_ping())
        message = Mumble_pb2.UserState()
        message.self_mute = True
        message.self_deaf = True
        yield from self.send_protobuf(version)
        yield from self.send_protobuf(auth)
        yield from self.send_protobuf(message)
        asyncio.Task(self.join_channel(self.channel))
        self.connected = True
        yield from self.read_loop()

    def die(self):
        pass

    def update_user(self, message):
        pass

    @asyncio.coroutine
    def handle_text_message(self, message):
        try:
            actor = self.users.by_session(message.actor)
            info("Message from {0}: {1}", actor,
                 message.message)
            m = {}
        except KeyError:
            critical("Unknown actor in handle_text_message")
            return
        m['origin'] = actor
        m['private'] = False
        if len(message.session) > 0:  # It's directed as a private message
            info("Received private")
            m['destination'] = self.own_user
            m['private'] = True
        elif message.channel_id:
            info("Received channel message")
            m['destination'] = self.channel_manager.get(message.channel_id[0])
        else:
            info("Received tree message")
            m['destination'] = None
            return m
        m['message'] = message.message
        try:
            x = yield from self.command_manager.handle_message(m)
        except NewBot as e:
            self.create_bot(*e.args[0])
            yield from self.send_text_message("Creating new bot.", m['origin'])
            return
        if isinstance(x, str):
            if m['destination'] == self.get_channel(self.channel):
                s = m['destination']
            else:
                s = m['origin']
            yield from self.send_text_message(x, s)

    def get_channel(self, name) -> Channel:
        if name.isdigit():
            return self.channel_manager.get(name)
        else:
            return self.channel_manager.get_by_name(name)

    @asyncio.coroutine
    def join_channel(self, channel):
        if isinstance(channel, str):
            channel = self.get_channel(channel)
        if channel is None:
            return False
        if isinstance(channel, Channel):
            channel = channel.id
        msg = Mumble_pb2.UserState()
        msg.channel_id = channel

        yield from self.send_protobuf(msg)
        return True

    def create_bot(self, name, channel):
        print("Creating bot.", name, channel)
        p = Protocol('mumble.koalabeast.com', name=name, channel=channel)
        asyncio.Task(p.connect())

    @asyncio.coroutine
    def user_joined_channel(self, u):
        if self.group_manager.group:
            l = self.group_manager.group.group_link
            yield from self.send_text_message("Hi, I'm the PUGBot for this "
                                              "channel! The current group "
                                              "link is <a href='{}'>{}</a>"
                                              "".format(l, l), u)

    def start_bots(self):
        with open("bots") as f:
            bots = f.read()
        for n, c in [x.rstrip().split(",") for x in bots.splitlines()]:
            asyncio.Task(
                Protocol("mumble.koalabeast.com", name=n, channel=c).connect())


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    p = Protocol("mumble.koalabeast.com", name="RectalBot",
                 channel="Rectal Rangers 3D", root=True)
    try:
        # p = Protocol()
        asyncio.Task(p.connect())
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        info("Shutting down.")
    finally:
        Session().query(User).delete()
        Session().commit()