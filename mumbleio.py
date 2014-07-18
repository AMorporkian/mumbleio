# !/usr/bin/env python
# coding=utf-8
import platform
import struct
import ssl
import asyncio

import logbook

import Mumble_pb2
from channels import ChannelManager
from commands import CommandManager, NewBot
from db import User, Channel, Session
from message_handler import MessageHandler
from tagpro import GroupManager
from users import UserManager


logger = logbook.Logger("mumbleio")


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

    def __init__(self, host="mumble.koalabeast.com", name="ChangeThis",
                 channel=None, root=False,
                 home_server="origin", start_group=True):
        self.pinger = asyncio.Task(self.init_ping())
        self.bots.append(self)

        self.user_manager = UserManager()
        self.channel_manager = ChannelManager()
        self.group_manager = GroupManager(self)
        self.command_manager = CommandManager(self, self.user_manager)
        self.message_handler = MessageHandler(self, self.channel_manager, self.user_manager)

        self.reader = None
        self.writer = None
        self.username = name
        self.host = host
        self.home_server = home_server

        self.own_user = None
        self._connected = False
        self._should_start_group = start_group

        self.channel = channel

        if root:
            self.start_bots()

    def connected(self):
        if self.connection_lock.locked():
            self.connection_lock.release()  # We're as connected as possible.
        if self.home_server and self._should_start_group:
            asyncio.Task(self.group_manager.new_group(server=self.home_server))

    def read_loop(self):
        try:
            try:
                while self._connected:

                    header = yield from self.reader.readexactly(6)
                    message_type, length = struct.unpack(Protocol.PREFIX_FORMAT,
                                                         header)
                    if message_type not in Protocol.MESSAGE_ID.values():
                        logger.critical("Unknown ID, exiting.")
                        self.die()
                    raw_message = (yield from self.reader.readexactly(length))
                    message = Protocol.ID_MESSAGE[message_type]()
                    message.ParseFromString(raw_message)
                    asyncio.Task(self.message_handler.handle_message(message))
            except asyncio.IncompleteReadError:
                logger.critical("Disconnected. Reconnecting...")
            except GeneratorExit:
                self._connected = False
        finally:
            self.pinger.cancel()
            self.writer.close()
            if not self._connected:
                self.bots.remove(self)
            if not self.bots:
                l = asyncio.get_event_loop()
                l.stop()
            if self._connected:
                yield from self.reconnect()


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
            if self._connected:
                yield from self.send_protobuf(Mumble_pb2.Ping())


    @asyncio.coroutine
    def connect(self):
        logger.info("Connecting...")
        yield from self.connection_lock
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        ssl_context.load_cert_chain("keys/public.cert", "keys/private.key")
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

        message = Mumble_pb2.UserState()
        message.self_mute = True
        message.self_deaf = True

        yield from self.send_protobuf(version)
        yield from self.send_protobuf(auth)
        yield from self.send_protobuf(message)
        self._connected = True
        yield from self.read_loop()

    def die(self):
        self._connected = False

    def update_user(self, message):
        pass

    @asyncio.coroutine
    def handle_text_message(self, message):
        try:
            actor = self.user_manager.by_session(message.actor)
            logger.info("Message from {0}: {1}", actor,
                        message.message)
            m = {}
        except KeyError:
            logger.critical("Unknown actor in handle_text_message")
            return
        m['origin'] = actor
        m['private'] = False
        if len(message.session) > 0:  # It's directed as a private message
            logger.info("Received private")
            m['destination'] = self.own_user
            m['private'] = True
        elif message.channel_id:
            logger.info("Received channel message")
            m['destination'] = self.channel_manager.get(message.channel_id[0])
        else:
            logger.info("Received tree message")
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
            if m['destination'] == self.own_user.channel:
                s = m['destination']
            else:
                s = m['origin']
            yield from self.send_text_message(x, s)

    @asyncio.coroutine
    def join_channel(self, channel):
        if isinstance(channel, str):
            channel = self.channel_manager.get(channel)
        if channel is None:
            return False
        if isinstance(channel, Channel):
            channel = channel.id
        msg = Mumble_pb2.UserState()
        msg.channel_id = channel

        yield from self.send_protobuf(msg)
        return True

    def create_bot(self, name, channel, home_server="origin"):
        logger.info("Creating bot.", name, channel)
        p = Protocol('mumble.koalabeast.com', name=name, channel=channel)
        asyncio.Task(p.connect())

    @asyncio.coroutine
    def user_joined_channel(self, u):
        if self.group_manager.group:
            l = self.group_manager.group.group_link

    def start_bots(self):
        with open("bots") as f:
            bots = f.read()
        for n, c, s in [x.rstrip().split(",") for x in bots.splitlines()]:
            asyncio.Task(
                Protocol("mumble.koalabeast.com", name=n, channel=c,
                         home_server=s).connect())

    @asyncio.coroutine
    def reconnect(self):
        yield from asyncio.sleep(5)
        asyncio.Task(self.connect())


if __name__ == "__main__":
    setup = logbook.NestedSetup([logbook.NullHandler(),
                                 logbook.StderrHandler(level='INFO',
                                                       bubble=True),
                                 logbook.FileHandler('mumbleio.log',
                                                     level='DEBUG',
                                                     bubble=True)])
    loop = asyncio.get_event_loop()
    p = Protocol("mumble.koalabeast.com", name="AFKBot",
                 channel="Recharging Station", root=True,
                 start_group=False)
    try:
        with setup.applicationbound():
            asyncio.Task(p.connect())
            loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down.")
    finally:
        Session().query(User).delete()
        Session().query(Channel).delete()
        Session().commit()
