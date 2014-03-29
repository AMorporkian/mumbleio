#!/usr/bin/env python
# coding=utf-8
from http.cookies import SimpleCookie
import json
import platform
import shelve
import struct
import uuid
import time
import ssl
import asyncio
import re

import aiohttp
import logbook
import websockets
from logbook import critical, warning, info, debug

import Mumble_pb2


def link(url):
    return '<a href="%s">%s</a>' % (url, url)


class Permission:
    def __init__(self, name):
        self.name = name


owner = Permission("owner")
admin = Permission("admin")
linker = Permission("linker")
grouper = Permission("grouper")
all_perms = {x.name: x for x in [owner, admin, linker, grouper]}
owner_hash = '91d57205a2841e07c699ee587f05852ea070f699'
logger = logbook.StderrHandler()
logger.push_application()

message_parser = r'(?P<type>\d):(?P<id>[^:]?):(?P<endpoint>[^:]*):(?P<data>.*)'


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args,
                                                                 **kwargs)
        return cls._instances[cls]


class TagproMember:
    def __init__(self, *, name, id, location="???", spectator, leader,
                 lastSeen):
        self.name = name
        self.id = id
        self.location = location
        self.spectator = spectator
        self.leader = leader
        self.lastSeen = lastSeen

    def update(self, d):
        for k, v in d.items():
            setattr(self, k, v)


class Tagpro:
    def __init__(self, join_cb=None, server="origin"):
        if server.lower() not in ['pi', 'origin', 'sphere', 'centra', 'chord',
                                  'diameter', 'tangent']:
            raise ValueError("Unknown server.")
        if server.lower() != 'tangent':
            x = "http://tagpro-%s.koalabeast.com/groups/create/" % server
        else:
            x = "http://tangent.jukejuice.com/groups/create/"
        self.server = server
        self.group_create_link = x
        self.token = None
        self.name = "Auto-generated PUG %s" % uuid.uuid4()
        self.cookie = None
        self.group_space = None
        self.socket = None
        self.connected = False
        self._thumper = None
        self.group_loop = None
        self.us = None
        self.member_ids = set()
        if join_cb is None:
            join_cb = lambda *args, **kwargs: None
        self.join_cb = join_cb
        self.members = {}
        self.game_settings = {""}
        self.session = aiohttp.Session()
        self.socket_link = ""
        #self.session.update_cookies({"music": "false", "sound": "false"})


    @asyncio.coroutine
    def send_text(self, text):
        yield from self.send(
            '5::%s:{"name":"chat","args":["%s"]}' % (self.group_space, text))

    @property
    def headers(self):
        return {
            "Referer": self.group_link,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/33.0.1750.146 Safari/537.36",
            "Accept-Encoding": "gzip,deflate,sdch",
            "Accept-Language": "en-US,en;q=0.8"
        }

    @asyncio.coroutine
    def leave(self):
        try:
            yield from self.socket.close()
            yield from self.socket.close_connection()
            self.socket = None
            self.group_loop.cancel()
            self.group_loop = None
        except Exception as e:
            critical(e)
        x = yield from aiohttp.request("GET",
                                       "http://tagpro-%s.koalabeast.com/groups/leave/" % self.server,
                                       cookies=self.cookies,
                                       headers=self.headers,
                                       allow_redirects=False)  # cookies={"tagpro": self.cookie}, headers=headers)
        x.close()
        print("Here yo")


    @asyncio.coroutine
    def give_up_leader(self):
        yield from self.send_text("PUGBot is giving up control.")
        yield from self.leave()

        #yield from asyncio.sleep(10)
        print("Starting group")
        yield from self.get_token()
        yield from self.start_group()

    @asyncio.coroutine
    def get_cookie(self):
        response = (yield from aiohttp.request('GET',
                                               'http://tagpro-%s.koalabeast.com' % self.server,
                                               headers=self.headers))
        response.close()
        self.update_cookies(response)
        #self.session.update_cookies({"tagpro": response.cookies['tagpro'].value})
        #self.cookie = response.cookies['tagpro'].value

    def update_cookies(self, response):
        jar = response.cookies
        if self.cookie is None:
            self.cookie = jar
        else:
            print("Changing cookies.")
            print("Old: %s" % self.cookie['tagpro'].value)
            self.cookie.update(jar)
            print("New: %s" % self.cookie['tagpro'].value)


    @property
    def cookies(self):
        return {k: v.value for k, v in self.cookie.items()}

    @asyncio.coroutine
    def create_group(self):
        debug("Creating group")
        if self.cookie is None:
            yield from self.get_cookie()

        r = (yield from aiohttp.request("POST", self.group_create_link,
                                        data=json.dumps(
                                            {"name": "PUGBot's Realm"}),
                                        cookies=self.cookies))
        r.close()
        self.group_space = r.url
        #print(r)
        self.update_cookies(r)
        #print(self.cookie)
        yield from asyncio.sleep(1)
        r2 = (yield from aiohttp.request("GET", self.group_link,
                                         cookies=self.cookies, ))
        #session=self.session))
        body = yield from r2.read()
        #print("Status:", r2)
        #print("Body:", body)
        #self.cookie = r2.cookies['tagpro'].value
        #print(r2)
        self.update_cookies(r2)
        return self.group_space

    @asyncio.coroutine
    def get_token(self):
        req = aiohttp.request('GET',
                              'http://tagpro-%s.koalabeast.com:81/socket.io/1' %
                              self.server,
                              cookies=self.cookies)
        response = (yield from req)
        #session=self.session))
        response.close()
        data = (yield from response.read())
        self.token = data.decode("ascii").split(":")[0]

    @asyncio.coroutine
    def change_name(self):
        yield from self.send('5::%s:{"name":"name","args":["PUGBot"]}")' % self.group_space)

    @asyncio.coroutine
    def start_group(self):
        if self.group_loop is None:
            self.group_loop = asyncio.Task(self._start_group())
        return self.group_loop

    @asyncio.coroutine
    def _start_group(self):
        try:
            if self.group_space is None:
                yield from self.create_group()
            if self.token is None:
                yield from self.get_token()
            #print("ws://tagpro-%s.koalabeast.com:81/socket.io/1/websocket/%s" % (self.server, self.token))
            print(self.socket)
            websocket = yield from websockets.connect(
                "ws://tagpro-%s.koalabeast.com:81/socket.io/1/websocket/%s" % (
                    self.server, self.token))  #, cookies=self.cookie)

            self.socket = websocket
            print((yield from websocket.recv()))  # Connection
            yield from self.send(
                "1::%s" % self.group_space)  # Get the namespace
            self._thumper = asyncio.Task(self.thumper())
            yield from self.change_name()
            while True:
                data = (yield from websocket.recv())
                if data is None:
                    debug("It's dead!")
                    #yield from self.leave()
                    yield from self.socket.close()
                    yield from self.socket.close_connection()
                    self.socket = None
                    return

                if data[0] == "0":
                    debug("Got a disconnect, reconnecting.")
                    debug("Not reconnecting.")
                    return

                if data[0] == '5':
                    try:
                        yield from self.event_handler(data)
                    except InterruptedError:
                        debug("Exiting read loop.")
                        break
                    except ConnectionError as e:
                        print(e)
                        print("Connection error")
                        break
        finally:
            if self._thumper is not None:
                self._thumper.cancel()
                self._thumper = None

    @asyncio.coroutine
    def event_handler(self, event):
        match = re.match(message_parser, event)
        data = json.loads(match.group("data"))
        debug(data)
        if data['name'] == "member":
            id = data['args'][0]['id']
            print(id)
            print(self.member_ids)
            if id not in self.member_ids:
                self.member_ids.add(id)
                x = TagproMember(**data['args'][0])
                self.members[x.name] = x
                debug("Added name {}", x.name)
                if self.us is not None:
                    yield from self.send_text("Hi, I'm PUGBot. I'm super cool.")
                    self.join_cb(x.name)
                    if self.us.leader and id != self.us.id:
                        asyncio.Task(self.give_up_leader())
                        self.member_ids.remove(self.us.id)
                        del (self.members[self.us.name])
                        self.us = None
            else:
                try:
                    member = [x for x in self.members.values() if x.id == id][0]
                    member.update(data['args'][0])
                except IndexError:
                    pass

        elif data['name'] == 'you':
            id = data['args'][0]
            self.us = [x for x in self.members.values() if x.id == id][0]
            debug("Got us.")
        elif data['name'] == 'removed':
            try:
                self.members.pop(data['args'][0]['id'])
            except LookupError:
                debug("Tried to remove a non-existent ID.")
                #self.part_cb(data['args'][0]['name'])

    @asyncio.coroutine
    def send(self, data):
        debug("Sending {}", data)
        yield from self.socket.send(data)

    @asyncio.coroutine
    def thumper(self):
        """Sends a periodic heartbeat."""
        print(self.socket)
        while self.socket is not None:
            yield from self.send("2::")
            yield from self.send(
                '5::%s:{"name":"touch","args":["page"]}' % self.group_space)
            yield from asyncio.sleep(5)
            debug("Thump")

    @property
    def group_link(self):
        return 'http://tagpro-%s.koalabeast.com%s' % (
        self.server, self.group_space)


class Restrict:
    def __init__(self, permission):
        """
        If there are decorator arguments, the function
        to be decorated is not passed to the constructor!
        """
        self.perm = permission

    def __call__(self, f):
        debug("In __call__")

        @asyncio.coroutine
        def wrapped_f(s, source, *args):
            if self.perm.name in source.permissions:
                debug("Allowing")
                return (yield from f(s, source, *args))
            else:
                debug("Not allowed!")
                raise PermissionError(self.perm)

        return wrapped_f


class CommandManager:
    def __init__(self, protocol):
        self.prefix = "."
        self.protocol = protocol
        self.commands = {
            "create_group": self.create_group,
            "set_link": self.set_link,
            "add_linker": self.add_linker,
            "del_linker": self.del_linker,
            "join": self.join,
            "help": self.help,
            "hash": self.ret_hash,
            "add_perm": self.add_perm}
        self.um = UserManager()
        print(self.commands)

    def ret_hash(self, origin, *args):
        return origin.hash

    @asyncio.coroutine
    def handle_message(self, message):
        split_message = message['message'].split()

        if split_message[0][0] == self.prefix and split_message[0][
                                                  1:] in self.commands:
            try:
                f = self.commands[split_message[0][1:]]
                x = (yield from f(message['origin'], message['destination'],
                                  split_message[1:]))
                return x
            except PermissionError:
                return "Sorry, you don't have the permissions to do that."

    @Restrict(grouper)
    def create_group(self, source, target, *args):
        gl = yield from self.protocol.group_manager.new_group()
        return "Here's the group link! %s" % link(gl)

    @Restrict(linker)
    def set_link(self, source, target, *args):
        pass

    @Restrict(admin)
    def add_linker(self, source, target, *args):
        pass

    @Restrict(admin)
    def del_linker(self, source, target, *args):
        pass

    @Restrict(admin)
    def join(self, source, target, args):
        try:
            channel = self.protocol.get_channel(" ".join(args))
            yield from self.protocol.join_channel(channel)
            yield from self.protocol.send_text_message("I have arrived!",
                                                       channel)
        except KeyError as e:
            yield from self.protocol.send_text_message(str(e), source)


    def get_perm(self, perm):
        return all_perms[perm]

    @Restrict(owner)
    def add_perm(self, source, target, args):
        name = " ".join(args[:-1])
        perm = args[-1].lower()
        try:
            p = self.get_perm(perm)
            u = self.um.by_name(name)
            u.add_permission(p)
        except KeyError as e:
            critical(e)
            return str(e)

    def help(self, source, target, *args):
        debug("In help")


class GroupManager:
    def __init__(self, protocol):
        self.protocol = protocol
        self.groups = {}

    @asyncio.coroutine
    def new_group(self, server=None):
        if server is not None:
            group = Tagpro(self.join_announcer, server)
        else:
            group = Tagpro(self.join_announcer)
        gid = yield from group.create_group()
        self.groups[gid] = group
        debug("Starting group {}", gid)
        asyncio.Task(group.start_group())
        debug("Returning from new_group")
        return group.group_link

    def join_announcer(self, name):
        c = self.protocol.channel_manager.get(self.protocol.own_user.channel_id)

        debug("Here")
        asyncio.Task(
            self.protocol.send_text_message("%s has joined the PUG." % name, c))


class User:
    attrs = dict(session=None, actor=None, name="", user_id=-1,
                 channel_id=-1, mute=False, deaf=False, suppress=False,
                 self_mute=False, self_deaf=False, texture=None,
                 plugin_context=None, plugin_identity=None, comment="",
                 hash=None, comment_hash=None, texture_hash=None,
                 priority_speaker=False, recording=False)

    def __init__(self, *, session=None, actor=None, name="", user_id=-1,
                 channel_id=-1, mute=False, deaf=False, suppress=False,
                 self_mute=False, self_deaf=False, texture=None,
                 plugin_context=None, plugin_identity=None, comment="",
                 hash=None, comment_hash=None, texture_hash=None,
                 priority_speaker=False, recording=False):
        debug("Creating user.")
        self.session = session
        self.actor = actor
        self.name = name
        self.user_id = user_id
        self.channel_id = channel_id
        self.mute = mute
        self.deaf = deaf
        self.suppress = suppress
        self.self_mute = self_mute
        self.self_deaf = self_deaf
        self.texture = texture
        self.plugin_context = plugin_context
        self.plugin_identity = plugin_identity
        self.comment = comment
        self.hash = hash
        self.comment_hash = comment_hash
        self.texture_hash = texture_hash
        self.priority_speaker = priority_speaker
        self.recording = recording
        self.permissions = set()

    def add_permission(self, perm):
        if isinstance(perm, Permission):
            perm = perm.name
        self.permissions.add(perm)

    def del_permission(self, perm):
        if isinstance(perm, Permission):
            perm = perm.name
        self.permissions.remove(perm)

    def update_from_message(self, message: Mumble_pb2.message):
        for k, v in message.ListFields():
            debug("Updating {} to {}", k.name, v)
            setattr(self, k.name, v)

    @classmethod
    def from_message(cls, message):
        debug("Creating user from message.")
        nd = {}
        for attr, default in cls.attrs.items():
            try:
                nd[attr] = getattr(message, attr)
            except AttributeError:
                continue
        return cls(**nd)

    def __str__(self):
        return "<User object for %s, session %d>" % (self.name, self.session)

    def __repr__(self):
        return self.__str__()


class UserManager(metaclass=Singleton):
    def __init__(self):
        debug("Creating user manager")
        self.shelf = shelve.open("users", writeback=True)
        if not 'users' in self.shelf:
            self.shelf['users'] = {}
        self.users = self.shelf['users']
        for user in self.users.values():
            debug(user.name)

    def add_user(self, user: User):
        if user.hash is None:
            raise ValueError("User doesn't have a hash.")
        if user.hash == owner_hash:
            for perm in all_perms.keys():
                user.add_permission(perm)
        self.users[user.hash] = user


    def by_name(self, name):
        for user in self.users.values():
            if user.name.lower() == name.lower():
                return user
        raise KeyError

    def from_message(self, message):
        if message.hash in self.users:
            u = self.users[message.hash]
            debug("Getting existing user.")
            print(message)
            u.update_from_message(message)

        else:
            debug("Creating new user")
            u = User.from_message(message)
            self.add_user(u)
        return u

    def by_x(self, a, x):
        for user in self.users.values():
            if getattr(user, a) == x:
                return user
        raise KeyError

    def check_by_x(self, a, x):
        try:
            self.by_x(a, x)
            return True
        except KeyError:
            return False

    def by_actor(self, id):
        debug(self.users.values())
        for user in self.users.values():
            #debug("Hello")
            # debug("{}, {}, {}",user.actor, id, user.actor==id)
            if user.session == id:
                return user
        raise KeyError

    def by_hash(self, hash):
        debug(self.users.values())
        for user in self.users.values():
            debug("Hello")
            debug("{}, {}, {}", user.hash, hash, user.hash == hash)
            if user.session == id:
                return user
        raise KeyError

    def save(self):
        self.shelf.close()
        self.shelf.sync()
        debug("Saved users.")


class ChatManager:
    def __init__(self):
        pass


class ChannelManager:
    def __init__(self):
        debug("Creating channel manager.")
        self.channels = {}

    def add_channel(self, id, parent=None, name=None, links=None,
                    description=None, links_add=None, links_remove=None,
                    temporary=None, position=None, description_hash=None):
        debug("Creating channel {0}", id)
        if id in self.channels:
            self.update_channel(id, parent, name, links, description, links_add,
                                links_remove, temporary, position,
                                description_hash)
        channel = Channel(id, parent, name, links, description, links_add,
                          links_remove, temporary, position, description_hash)
        if parent is not None and parent != 0:
            if parent not in self.channels:
                raise KeyError("Got a child channel without a root channel (?)")
            self.channels[parent].children.add(channel)
        self.channels[id] = channel

    def del_channel(self, id):
        try:
            del self.channels[id]
            info("Deleted channel with ID {0}", id)
        except KeyError:
            warning("Server removed channel with ID {0}, "
                    "but we haven't seen it before!", id)

    def get_by_name(self, name):
        for id, channel in self.channels.items():
            if channel.name.lower() == name.lower():
                return channel
        raise KeyError("Couldn't find a channel with the name %s" % name)

    def get(self, id):
        if not isinstance(id, int):
            if not id.isdigit():
                id = self.get_by_name(id).id
            else:
                id = int(id)
        return self.channels[id]

    def update_channel(self,
                       *args):  #id, parent, name, links, description, links_add,
        #links_remove, temporary, position, description_hash):
        print(args)

    def add_from_message(self, message):
        args = []
        for m in (
                'channel_id', 'parent', 'name', 'links', 'description',
                'links_add',
                'links_remove', 'temporary', 'position', 'description_hash'):
            args.append(getattr(message, m, None))
        self.add_channel(*args)


class Channel:
    def __init__(self, id, parent, name, links, description, links_add,
                 links_remove, temporary, position, description_hash):
        self.id = id
        self.name = name
        self.position = position
        self.parent = parent
        self.links = links
        self.description = description
        self.links_add = links_add
        self.links_remove = links_remove
        self.temporary = temporary
        self.description_hash = description_hash
        self.users = UserManager()
        self.children = set()


class Protocol:
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

    def __init__(self, host="mumble.koalabeast.com", username="TesterBot",
                 user_manager=None):
        self.username = username
        self.host = host
        self.users = UserManager()
        self.channels = {}
        self.own_user = None
        self.channel_manager = ChannelManager()
        self.command_manager = CommandManager(self)
        self.group_manager = GroupManager(self)

    def read_loop(self):
        try:
            while True:
                header = yield from self.reader.readexactly(6)
                message_type, length = struct.unpack(Protocol.PREFIX_FORMAT,
                                                     header)
                if message_type not in Protocol.MESSAGE_ID.values():
                    print("Unknown ID")
                    self.die()
                raw_message = (yield from self.reader.readexactly(length))
                message = Protocol.ID_MESSAGE[message_type]()
                message.ParseFromString(raw_message)
                yield from self.mumble_received(message)
        except (KeyboardInterrupt, SystemExit):
            self.users.save()
            return


    @asyncio.coroutine
    def mumble_received(self, message):
        #print(message)
        if isinstance(message, Mumble_pb2.Version):
            debug("Version received")

        elif isinstance(message, Mumble_pb2.Reject):
            critical("Rejected")
            self.die()
            self.pinging = False

        elif isinstance(message, Mumble_pb2.CodecVersion):
            debug("Received codecversion")
        elif isinstance(message, Mumble_pb2.CryptSetup):
            debug("Received crypto setup")
        elif isinstance(message, Mumble_pb2.ChannelState):
            info("Received channel state")
            self.channel_manager.add_from_message(message)
        elif isinstance(message, Mumble_pb2.PermissionQuery):
            debug("Received permissions query", message)
        elif isinstance(message, Mumble_pb2.UserState):
            info("Received userstate")
            info(self.users)
            if self.own_user is None:
                info("Creating own user")
                self.own_user = self.users.from_message(message)
            elif message.session == self.own_user.session:
                info("Updating own user")
                self.own_user.update_from_message(message)
            elif self.users.check_by_x("session", message.session):
                info("Updating other user")
                self.users.by_x("session", message.session).update_from_message(
                    message)
            else:
                info("Creating new user.")
                self.users.from_message(message)
        elif isinstance(message, Mumble_pb2.ServerSync):
            info("Received welcome message")
        elif isinstance(message, Mumble_pb2.ServerConfig):
            info("Received server config")
        elif isinstance(message, Mumble_pb2.Ping):
            #debug("Received ping")
            pass
        elif isinstance(message, Mumble_pb2.UserRemove):
            info("Received UserRemove")
        elif isinstance(message, Mumble_pb2.TextMessage):
            info("Received text message")
            info(message)
            yield from self.handle_text_message(message)
        elif isinstance(message, Mumble_pb2.ChannelRemove):
            info("Received channel remove")
            self.channel_manager.del_channel(message.channel_id)
        #elif isinstance(message, Mumble_pb2.)
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
        info(m)
        print(m)
        print(m.channel_id)
        yield from self.send_protobuf(m)

    @asyncio.coroutine
    def init_ping(self):
        while True:
            yield from asyncio.sleep(Protocol.PING_REPEAT_TIME)
            yield from self.send_protobuf(Mumble_pb2.Ping())

    @asyncio.coroutine
    def ping_handler(self):
        if not self.pinging:
            return

    @asyncio.coroutine
    def connect(self):
        info("Connecting...")
        sslcontext = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        #sslcontext.options |= ssl.CERT_NONE
        self.reader, self.writer = (
            yield from asyncio.open_connection(self.host, 64738,
                                               server_hostname='',
                                               ssl=sslcontext))

        version = Mumble_pb2.Version()
        version.version = Protocol.VERSION_DATA
        version.release = "%d.%d.%d" % (Protocol.VERSION_MAJOR,
                                        Protocol.VERSION_MINOR,
                                        Protocol.VERSION_PATCH)
        version.os = platform.system()
        version.os_version = "Mumble %s asyncio" % version.release

        auth = Mumble_pb2.Authenticate()
        auth.username = self.username
        asyncio.Task(self.init_ping())
        message = Mumble_pb2.UserState()
        message.self_mute = True
        message.self_deaf = True
        yield from self.send_protobuf(version)
        yield from self.send_protobuf(auth)
        yield from self.send_protobuf(message)
        yield from self.read_loop()


    def die(self):
        pass

    def update_user(self, message):
        print(message)

    @asyncio.coroutine
    def handle_text_message(self, message):
        try:
            actor = self.users.by_actor(message.actor)
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
        x = yield from self.command_manager.handle_message(m)
        if isinstance(x, str):
            yield from self.send_text_message(x, m['destination'])

    @asyncio.coroutine
    def handle_command(self, message):
        m = message['message'].split()
        l = [x.lower() for x in m]
        if l[0] == 'list':
            for channel in self.channel_manager.channels.values():
                info("Sending {0}", channel.name)
                yield from self.send_text_message(channel.name, m['origin'])

        elif l[0] == 'join':
            try:
                channel = self.get_channel(" ".join(l[1:]))
                yield from self.join_channel(channel)
                print(channel)
                yield from self.send_text_message("I have arrived!", channel)
            except KeyError as e:
                yield from self.send_text_message(str(e), message['origin'])

        elif l[0] == 'create_group':
            x = Tagpro()
            l = yield from x.create_group()
            print(l)
            asyncio.Task(x.start_group())
            #group_id = yield from self.tagpro.create_group()
            #info("Created group with ID {}", group_id)
            #yield from self.tagpro.connect_bot(group_id)

    def get_channel(self, name):
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


if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        p = Protocol("127.0.0.1")
        #p = Protocol()
        asyncio.Task(p.connect())
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        info("Shutting down.")
    finally:
        UserManager().save()

