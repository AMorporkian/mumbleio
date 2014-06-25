import shelve

from logbook import debug

import Mumble_pb2
from permissions import Permission, all_perms
from utilities import Singleton


owner_hash = '91d57205a2841e07c699ee587f05852ea070f699'

__author__ = 'ankhmorporkian'


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
        if perm in self.permissions:
            return False
        else:
            self.permissions.add(perm)
            return True

    def del_permission(self, perm):
        if isinstance(perm, Permission):
            perm = perm.name
        if perm in self.permissions:
            self.permissions.remove(perm)
            return True
        else:
            return False

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

    def add_user(self, user: User):
        if user.hash is None:
            raise ValueError("User doesn't have a hash.")
        if user.hash == owner_hash:
            for perm in all_perms.keys():
                user.add_permission(perm)
        self.users[user.hash] = user


    def by_name(self, name) -> User:
        for user in self.users.values():
            if user.name.lower() == name.lower():
                return user
        raise KeyError

    def from_message(self, message):
        if message.hash in self.users:
            u = self.users[message.hash]
            debug("Getting existing user.")
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
            # debug("Hello")
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