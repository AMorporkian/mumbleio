import shelve

from logbook import debug, warning
from sqlalchemy import func

from db import User, Session, Permissions
from permissions import all_perms, owner

owner_hash = '91d57205a2841e07c699ee587f05852ea070f699'

__author__ = 'ankhmorporkian'


class UserManager():
    def __init__(self):
        self.session = Session()

    def add_user(self, user: User):
        if user.hash is None:
            raise ValueError("User doesn't have a hash.")
        if user.hash == owner_hash:
            for perm in all_perms.keys():
                user.add_permission(perm)
        self.session.add(user)

    def by_name(self, name) -> User:
        return self.session.query(User).filter(
            func.lower(User.name) == func.lower(name)).first()

    def from_message(self, message):
        if message.hash:
            if not self.session.query(Permissions).get(message.hash):
                m = Permissions(hash=message.hash)
                if message.hash == owner_hash:
                    print("Got owner hash for the first time.")
                    m.add_permission(owner)
                self.session.add(m)
        u = self.session.query(User).filter_by(session=message.session).first()
        if u is not None:
            u.update_from_message(message)
        else:
            u = User.from_message(message)
            self.add_user(u)
        return u

    def by_actor(self, id):
        return self.session.query(User).filter_by(actor=id).first()

    def by_session(self, id):
        return self.session.query(User).filter_by(session=id).first()

    def by_hash(self, hash):
        return self.session.query(User).get(hash)