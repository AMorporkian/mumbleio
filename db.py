from logbook import debug, info
from sqlalchemy.orm import relationship, sessionmaker, scoped_session
import Mumble_pb2
from permissions import Permission
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, \
    create_engine

__author__ = 'ankhmorporkian'
Base = declarative_base()

class Channel(Base):
    __tablename__ = 'channel'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    position = Column(Integer)
    parent_id = Column(Integer, ForeignKey('channel.id'))
    links = Column(String)
    description = Column(String)
    links_add = Column(String)
    links_remove = Column(String)
    temporary = Column(String)
    description_hash = Column(String)
    users = relationship('User')
    children = relationship('Channel')

    def __repr__(self):
        return "<Channel: {} ({})>".format(self.name, self.id)


class User(Base):
    __tablename__ = 'user'

    attrs = dict(session=None, actor=None, name="", user_id=-1,
                 channel_id=-1, mute=False, deaf=False, suppress=False,
                 self_mute=False, self_deaf=False, texture=None,
                 plugin_context=None, plugin_identity=None, comment="",
                 hash=None, comment_hash=None, texture_hash=None,
                 priority_speaker=False, recording=False)


    session = Column(Integer, primary_key=True)
    hash = Column(String, ForeignKey('permissions.hash'))
    actor = Column(Integer)
    name = Column(String)
    user_id = Column(Integer)
    channel_id = Column(Integer, ForeignKey('channel.id'))
    mute = Column(Boolean)
    deaf = Column(Boolean)
    suppress = Column(Boolean)
    self_mute = Column(Boolean)
    self_deaf = Column(Boolean)
    texture = Column(String)
    plugin_context = Column(String)
    plugin_identity = Column(String)
    comment = Column(String)

    comment_hash = Column(String)
    texture_hash = Column(String)
    priority_speaker = Column(String)
    recording = Column(Boolean)
    channel = relationship("Channel", uselist=False)
    _permissions = relationship("Permissions", uselist=False)

    @property
    def permissions(self):
        if self._permissions is None:
            return set()
        return set(self._permissions.permissions)

    def add_permission(self, perm):
        if self._permissions:
            return self._permissions.add_permission(perm)

    def del_permission(self, perm):
        if self._permissions:
            return self._permissions.del_permission(perm)

    def update_from_message(self, message: Mumble_pb2.message):
        for k, v in message.ListFields():
            if getattr(self, k.name) != v:
                #print(k.name)
                if k.name == "self_mute":
                    if v:
                        info("{} is now muted.", self.name)
                    else:
                        info("{} is no longer muted.", self.name)
                elif k.name == "self_deaf":
                    if v:
                        info("{} is now deafened.", self.name)
                    else:
                        info("{} is no longer deafened.", self.name)
                elif k.name == "channel_id":
                    info("{} moved from {} to {}.", self.name, self.channel.name, Session().query(Channel).get(v).name)
                else:
                    print(k.name)
                setattr(self, k.name, v)

    @classmethod
    def from_message(cls, message):
        nd = {}
        for attr, default in cls.attrs.items():
            try:
                nd[attr] = getattr(message, attr)
            except AttributeError:
                continue
        return cls(**nd)

    def __str__(self):
        return "<User object for {}, session {}>".format(self.name, self.session)

    def __repr__(self):
        return self.__str__()


class Permissions(Base):
    __tablename__ = "permissions"

    hash = Column(String, primary_key=True)
    _permissions = Column(String, default="")

    @property
    def permissions(self):
        if self._permissions:
            return self._permissions.split(",")
        return set()

    def add_permission(self, perm):
        if isinstance(perm, Permission):
            for p in perm.subpermissions:
                print(p)
                self.add_permission(p)
            perm = perm.name
        if perm in self.permissions:
            return False
        else:
            p = set(self.permissions)
            p.add(perm)
            self._permissions = ",".join(p)
            return True

    def del_permission(self, perm):
        if isinstance(perm, Permission):
            perm = perm.name
        if perm in self.permissions:
            p = set(self.permissions)
            p.remove(perm)
            self._permissions = ",".join(p)
            return True
        else:
            return False


engine = create_engine('sqlite:///mumble.db', echo=False)
Base.metadata.create_all(engine)
Session = scoped_session(sessionmaker(bind=engine))
