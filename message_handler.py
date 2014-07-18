import asyncio

import logbook

import Mumble_pb2
from afk_handler import AFKHandler
from channels import ChannelManager
from users import UserManager


logger = logbook.Logger("message_handler")


class MessageHandler:
    def __init__(self, protocol, channel_manager: ChannelManager, user_manager: UserManager):
        self.protocol = protocol
        self.channel_manager = channel_manager
        self.user_manager = user_manager
        self.own_user = None
        self.dispatcher = {
            Mumble_pb2.Reject: self.rejected,
            Mumble_pb2.ChannelState: self.channel_state,
            Mumble_pb2.UserState: self.user_state,
            Mumble_pb2.UserStats: self.user_stats,
            Mumble_pb2.ServerConfig: self.server_config,
            Mumble_pb2.UserRemove: self.user_remove,
            Mumble_pb2.ChannelRemove: self.channel_remove,
            Mumble_pb2.TextMessage: self.text_message,
        }
        self.afk_handler = AFKHandler(protocol)

    @asyncio.coroutine
    def rejected(self, message):
        logger.critical("Connection rejected by server. Shutting down.")
        self.protocol.die()

    @asyncio.coroutine
    def channel_state(self, message):
        self.channel_manager.add_from_message(message)

    @asyncio.coroutine
    def user_state(self, message):
        if self.own_user is None:
            self.own_user = self.user_manager.from_message(message)
            self.protocol.own_user = self.own_user
            u = self.protocol.own_user
        elif message.session and message.session == self.own_user.session:
            self.own_user.update_from_message(message)
            u = self.own_user
        else:
            try:
                u = self.user_manager.from_message(message)
            except NameError:
                u = None

        if u and u is not self.own_user:
            u.connected = True

    @asyncio.coroutine
    def user_stats(self, message):
        self.afk_handler.handle_message(message)

    @asyncio.coroutine
    def server_config(self, message):
        self.protocol.connected()

    @asyncio.coroutine
    def user_remove(self, message):
        user = self.user_manager.by_session(message.session)
        if user:
            self.user_manager.remove_user(user)

    @asyncio.coroutine
    def text_message(self, message):
        yield from self.protocol.handle_text_message(message)

    @asyncio.coroutine
    def channel_remove(self, message: Mumble_pb2.ChannelRemove):
        channel = self.channel_manager.get(message.channel_id)
        self.channel_manager.del_channel(channel)

    @asyncio.coroutine
    def handle_message(self, message):
        for message_type, handler in self.dispatcher.items():
            if isinstance(message, message_type):
                if handler:
                    asyncio.Task(handler(message))

