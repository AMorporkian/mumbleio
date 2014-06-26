import asyncio

from logbook import critical, debug
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from db import User

from permissions import Restrict, grouper, admin, all_perms, owner, \
    Permission
from users import UserManager


__author__ = 'ankhmorporkian'


def link(url):
    return '<a href="%s">%s</a>' % (url, url)


class NewBot(Exception):
    pass


class CommandManager:
    def __init__(self, protocol, um):
        self.prefix = "."
        self.protocol = protocol
        self.commands = {
            "create_group": self.create_group,
            #"set_link": self.set_link,
            "join": self.join,
            "help": self.help,
            "hash": self.ret_hash,
            "add_perm": self.add_perm,
            "del_perm": self.del_perm,
            "add_bot": self.add_bot,
            "del_bot": self.del_bot,
            "list_bots": self.list_bots,
            "say": self.say,
            "whisper": self.whisper,
            "debug_permissions": self.debug_permissions,
            "whois": self.whois
        }
        self.um = um

    def ret_hash(self, origin, *args):
        return origin.hash

    @asyncio.coroutine
    def handle_message(self, message):
        split_message = message['message'].split()

        if split_message[0][0] == self.prefix and split_message[0][
                                                  1:] in self.commands:
            try:
                f = self.commands[split_message[0][1:]]
                if len(split_message) > 1:
                    x = (yield from f(message['origin'], message['destination'],
                                      *split_message[1:]))
                else:
                    x = (
                        yield from f(message['origin'], message['destination']))
                return x
            except PermissionError:
                return "Sorry, you don't have the permissions to do that."

    @Restrict(grouper)
    def create_group(self, source, target, *args):
        """Creates a group and has the bot manage it."""
        server = 'origin'
        if args:
            server = args[0]
        gl = yield from self.protocol.group_manager.new_group(server)
        return "Here's the group link! %s" % link(gl)

    @Restrict(admin)
    def join(self, source, target, *args):
        """Joins a channel."""
        try:
            channel = self.protocol.get_channel(" ".join(args))
            yield from self.protocol.join_channel(channel.id)
        except NoResultFound:
            yield from self.protocol.send_text_message("Couldn't find that channel.", source)
        except MultipleResultsFound:
            yield from self.protocol.send_text_message("There are multiple channels with that name.", source)

    @Restrict(admin)
    def add_bot(self, source, target, *args):
        """Adds a bot."""
        name = args[0]
        channel = " ".join(args[1:])
        raise NewBot((name, channel))

    @Restrict(admin)
    def list_bots(self, source, target, *args):
        """Lists all connected bots."""
        return "<br />Currently active bots: <br /><br />" + ("<br />".join(
            ["{}: <b>{}</b>".format(x.username, x.channel) for x in
             self.protocol.bots]))

    @Restrict(admin)
    def del_bot(self, source, target, args):
        for bot in self.protocol.bots:
            if bot.username.lower() == args.lower():
                bot.connected = False
                return "Disconnected the requested bot."

        else:
            return "Couldn't find a bot by the name {}. " \
                   "Please try the {}list_bots command to find the bot.".format(args, self.prefix)


    def get_perm(self, perm) -> Permission:
        return all_perms[perm]

    @Restrict(owner)
    def add_perm(self, source, target, *args):
        """Adds a permission by name."""
        name = " ".join(args[:-1])
        perm = args[-1].lower()
        try:
            p = self.get_perm(perm)
            print(p)
            print(p.subpermissions)
            u = self.um.by_name(name)
            if u.add_permission(p):
                yield from self.protocol.send_text_message("You've been given {} permissions by {}. Use them wisely.".format(p.name, source.name), u)
                return "Added permission {} to user {}.".format(p.name, u.name)
            else:
                return "User {} already had permission {}".format(u.name,
                                                                  p.name)


        except KeyError as e:
            critical(e)
            return str(e)

    @Restrict(owner)
    def del_perm(self, source, target, *args):
        name = " ".join(args[:-1])
        perm = args[-1].lower()
        try:
            p = self.get_perm(perm)
            u = self.um.by_name(name)
            if u.del_permission(p):
                yield from self.protocol.send_text_message(
                    "Your {} permissions have been revoked by {}.".format(
                        p.name, source.name), u)
                return "Removed permission {} from user {}.".format(p.name, u.name)
            else:
                return "User {} didn't have permission {}".format(u.name,
                                                                  p.name)
        except KeyError as e:
            critical(e)
            return str(e)

    @asyncio.coroutine
    def help(self, source, target, *args):
        return "<hr><center><b>Available commands:</b></center><hr>"+"<br />".join("<b>{}{}</b>: {}".format(self.prefix, s, t.__doc__) for s,t in self.commands.items() if t.__doc__ is not None)


    @Restrict(admin)
    def say(self, source, target, *args):
        yield from self.protocol.send_text_message(" ".join(args), self.protocol.channel_manager.get_by_name(self.protocol.channel))

    @Restrict(admin)
    def whisper(self, source, target, *args):
        yield from self.protocol.send_text_message(" ".join(args[1:]),
                                                   self.protocol.users.by_name(args[0]))

    @asyncio.coroutine
    def debug_permissions(self, source, target, *args):
        return "Your permissions: {}".format(self.protocol.users.by_name("AnkhMorpork").permissions)

    @Restrict(owner)
    def whois(self, source, target, name):
        p = self.um.by_name(name)
        if not p:
            return "User not found."
        return "<br />"+"<br />".join(["{}: {}".format(k,v) for k, v in [(k, getattr(p, k)) for k in User.attrs.keys()]])