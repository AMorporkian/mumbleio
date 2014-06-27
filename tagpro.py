import asyncio
import json
import re
import uuid

import aiohttp
import datetime
from logbook import critical, debug, info
import websockets


__author__ = 'ankhmorporkian'

websocket_parser = r'(?P<type>\d):(?P<id>[^:]?):(?P<endpoint>[^:]*):(?P<data>.*)'


class Game(object):
    def __init__(self, port, group):
        self.port = port
        self.group = group
        self.headers = group.headers



class Tagpro:
    def __init__(self, join_cb=None, leave_cb=None, server="origin"):
        if server.lower() not in ['pi', 'origin', 'sphere', 'centra', 'chord',
                                  'diameter', 'tangent', 'radius']:
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
        if leave_cb is None:
            leave_cb = lambda *args, **kwargs: None
        self.join_cb = join_cb
        self.leave_cb = leave_cb
        self.members = {}
        self.game_settings = {""}
        self.socket_link = ""
        self.name_changed = False
        self.last_gave_up = datetime.datetime.now()
        # self.session.update_cookies({"music": "false", "sound": "false"})

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


    @asyncio.coroutine
    def give_up_leader(self, player):
        if (datetime.datetime.now() - self.last_gave_up).total_seconds() >= 1:
            yield from self.send_text(
                "PUGBot is giving up control to {}.".format(player.name))
        yield from self.send('5::%s:{"name":"leader", "args": ["%s"]}' % (
        self.group_space, player.id))
        self.last_gave_up = datetime.datetime.now()

    @asyncio.coroutine
    def get_cookie(self):
        response = (yield from aiohttp.request('GET',
                                               'http://tagpro-%s.koalabeast.com' % self.server,
                                               headers=self.headers))
        response.close()
        self.update_cookies(response)

    def update_cookies(self, response):
        jar = response.cookies
        if self.cookie is None:
            self.cookie = jar
        else:
            self.cookie.update(jar)


    @property
    def cookies(self):
        return {k: v.value for k, v in self.cookie.items()}

    @asyncio.coroutine
    def create_group(self):
        info("Creating group")
        if self.cookie is None:
            yield from self.get_cookie()

        r = (yield from aiohttp.request("POST", self.group_create_link,
                                        data=json.dumps(
                                            {"name": "PUGBot's Realm"}),
                                        cookies=self.cookies))
        r.close()
        self.group_space = r.url

        self.update_cookies(r)

        yield from asyncio.sleep(1)
        r2 = (yield from aiohttp.request("GET", self.group_link,
                                         cookies=self.cookies, ))

        body = yield from r2.read()

        self.update_cookies(r2)
        return self.group_space

    @asyncio.coroutine
    def get_token(self):
        if self.cookie is None:
            yield from self.get_cookie()
        req = aiohttp.request('GET',
                              'http://tagpro-%s.koalabeast.com:443/socket.io/1' %
                              self.server,
                              cookies=self.cookies)
        response = (yield from req)

        response.close()
        data = (yield from response.read())
        self.token = data.decode("ascii").split(":")[0]

    @asyncio.coroutine
    def change_name(self):
        yield from self.send(
            '5::%s:{"name":"name","args":["PUGBot"]}' % self.group_space)
        self.name_changed = True

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

            websocket = yield from websockets.connect(
                "ws://tagpro-%s.koalabeast.com:443/socket.io/1/websocket/%s" % (
                    self.server, self.token))  # , cookies=self.cookie)

            self.socket = websocket
            yield from websocket.recv()  # Connection
            yield from self.send(
                "1::%s" % self.group_space)  # Get the namespace
            self._thumper = asyncio.Task(self.thumper())
            while True:
                data = (yield from websocket.recv())
                if data is None:
                    info("Group died.")
                    # yield from self.leave()
                    yield from self.socket.close()
                    yield from self.socket.close_connection()
                    self.socket = None
                    return

                if data[0] == "0":
                    return

                if data[0] == '5':
                    try:
                        yield from self.event_handler(data)
                    except InterruptedError:
                        break
                    except ConnectionError as e:
                        break
                if not self.name_changed:
                    yield from self.change_name()
                if self.us is not None and self.us.leader and len(self.members) > 1:
                    for m in self.members.values():
                        if m is self.us:
                            continue
                        yield from self.give_up_leader(m)
                        yield from asyncio.sleep(.25)

        finally:
            if self._thumper is not None:
                self._thumper.cancel()
                self._thumper = None

    @asyncio.coroutine
    def event_handler(self, event):
        match = re.match(websocket_parser, event)
        data = json.loads(match.group("data"))
        port_received = asyncio.Event()
        if data['name'] == "member":
            id = data['args'][0]['id']
            if id not in self.member_ids:
                self.member_ids.add(id)
                x = TagproMember(**data['args'][0])
                self.members[x.name] = x
                if self.us is not None:
                    self.join_cb(x.name)
            else:
                try:
                    member = [x for x in self.members.values() if x.id == id][0]
                    member.update(data['args'][0])
                except IndexError:
                    pass

        elif data['name'] == 'you':
            id = data['args'][0]
            self.us = [x for x in self.members.values() if x.id == id][0]
        elif data['name'] == 'port':
            self.port = data['args'][0]
            port_received.set()
        elif data['name'] == 'play':
            asyncio.Task(self.spectate(port_received))
        elif data['name'] == 'removed':
            self.remove_player(data['args'][0])
    @asyncio.coroutine
    def send(self, data):
        yield from self.socket.send(data)

    @asyncio.coroutine
    def thumper(self):
        """Sends a periodic heartbeat."""
        while self.socket is not None:
            yield from self.send("2::")
            yield from self.send(
                '5::%s:{"name":"touch","args":["page"]}' % self.group_space)
            yield from asyncio.sleep(5)

    @property
    def group_link(self):
        return 'http://tagpro-%s.koalabeast.com%s' % (
            self.server, self.group_space)

    def spectate(self, port_received):
        yield from port_received.wait()
        s = Game(self.port, self)
        score = yield from s.run()

    def remove_player(self, player):
        print("Removing")
        if player['name'] in self.members:
            print(player['name'])
            self.member_ids.remove(player['id'])
            del(self.members[player['name']])
            self.leave_cb(player['name'])


class TagproMember:
    def __init__(self, *, name, id, location="???", spectator, leader,
                 lastSeen, team, **kwargs):
        self.name = name
        self.id = id
        self.location = location
        self.spectator = spectator
        self.leader = leader
        self.lastSeen = lastSeen
        self.team = team

    def update(self, d):
        for k, v in d.items():
            setattr(self, k, v)


class GroupManager:
    def __init__(self, protocol):
        self.protocol = protocol
        self.group = None

    @asyncio.coroutine
    def new_group(self, server=None):
        if server is not None:
            group = Tagpro(self.join_announcer, self.leave_announcer, server)
        else:
            group = Tagpro(self.join_announcer, self.leave_announcer)
        gid = yield from group.create_group()


        debug("Starting group {}", gid)
        asyncio.Task(group.start_group())
        if self.group:
            yield from self.group.leave()
        self.group = group
        print(self.group.group_space)
        return group.group_link

    @asyncio.coroutine
    def existing_group(self, server, gs):
        group = Tagpro(self.join_announcer, self.leave_announcer, server)
        group.group_space = gs
        asyncio.Task(group.start_group())
        if self.group:
            yield from self.group.leave()
        self.group = group
        return group.group_link

    def join_announcer(self, name):
        c = self.protocol.channel_manager.get(self.protocol.own_user.channel_id)
        asyncio.Task(
            self.protocol.send_text_message("%s has joined the PUG." % name, c))

    def leave_announcer(self, name):
        c = self.protocol.channel_manager.get(self.protocol.own_user.channel_id)
        asyncio.Task(
            self.protocol.send_text_message("%s has left the PUG." % name, c))