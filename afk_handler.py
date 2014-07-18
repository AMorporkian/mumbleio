import asyncio

import logbook

import Mumble_pb2
from db import Session, User, Channel


logger = logbook.Logger("afk_handler")


class AFKHandler:
    loop_time = 60.0  # Time in seconds to wait between UserStats.
    backoff_time = .1  # Time in seconds to wait between moves.
    move_time = 3600  # Time in seconds to wait before determining a player is AFK
    afk_channel = 1281  # AFK channel to move players to
    roots = [1264, 1265]  # Root channels from which to apply AFK rules to

    def __init__(self, protocol):
        self.protocol = protocol
        self.user_manager = protocol.user_manager
        self.channel_manager = protocol.channel_manager
        self.afk_queue = []

        asyncio.Task(self.afk_loop())
        asyncio.Task(self.check_loop())

    @asyncio.coroutine
    def afk_loop(self):
        s = Session()
        yield from asyncio.sleep(5)
        while True:
            logger.debug("Running userstate update.")
            for u in s.query(User).filter(User.connected):
                m = Mumble_pb2.UserStats()
                m.session = u.session
                yield from self.protocol.send_protobuf(m)
            yield from asyncio.sleep(self.loop_time)

    @asyncio.coroutine
    def afk_check(self, session):
        u = self.user_manager.by_session(session)
        if u:
            logger.debug("Checking if {} is AFK", u.name)
            if 'bot' in u.name.lower():
                return
            is_in_root = any([self.channel_manager.get(x)
                              in u.channel.descendant_chain  #self.get_descendant_chain(u.channel)
                              for x in self.roots])
            if u.channel_id != self.afk_channel and is_in_root:
                logger.info("Moving {} to AFK for being AFK.".format(u.name))
                s = Mumble_pb2.UserState()
                s.session = session
                s.channel_id = self.afk_channel
                yield from self.protocol.send_protobuf(s)
                yield from self.protocol.send_text_message("You have been moved for being AFK.", u)

    def get_descendant_chain(self, channel: Channel):
        comp = channel
        r_list = [comp]
        while True:
            comp = self.channel_manager.get(comp.parent_id)
            if comp:
                r_list.append(comp)
                if comp is comp.parent_channel:
                    break
        return r_list

    @asyncio.coroutine
    def check_loop(self):
        while True:
            yield from asyncio.sleep(self.backoff_time)
            if self.afk_queue:
                yield from self.afk_check(self.afk_queue.pop())

    def handle_message(self, message):
        if message.idlesecs >= self.move_time:
            self.afk_queue.append(message.session)
