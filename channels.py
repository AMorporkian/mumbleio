from logbook import debug, info, warning

from db import Channel, Session


__author__ = 'ankhmorporkian'


class ChannelManager:
    def __init__(self):
        self.session = Session()

    def add_channel(self, id, parent=None, name=None, links=None,
                    description=None, links_add=None, links_remove=None,
                    temporary=None, position=None, description_hash=None):
        c = self.session.query(Channel).get(id)
        if c:
            debug("Updating channel {} ({})".format(c.name, id))
            self.update_channel(id, parent, name, links, description, links_add,
                                links_remove, temporary, position,
                                description_hash)
        else:
            c = Channel(id=id,
                        parent_id=parent, name=name, links="", description=description,
                        links_add="",links_remove="",
                        temporary=temporary, position=position,
                        description_hash=description_hash)
            self.session.add(c)

        if parent is not None and parent != 0:
            p = self.session.query(Channel).get(parent)
            if p is None:
                raise KeyError("Got a child channel without a root channel (?)")

    def del_channel(self, id):
        try:
            c = self.session.query(Channel).get(id)
            self.session.delete(c)
            info("Deleted channel with ID {0}", id)
        except KeyError:
            warning("Server removed channel with ID {}, "
                    "but we haven't seen it before!", id)
        except:
            pass

    def get_by_name(self, name):
        return self.session.query(Channel).filter_by(name=name).first()

    def get(self, id):
        if not isinstance(id, int):
            if not id.isdigit():
                id = self.get_by_name(id).id
            else:
                id = int(id)
        return self.session.query(Channel).get(id)

    def update_channel(self,
                       *args):  # id, parent, name, links, description, links_add,
        #links_remove, temporary, position, description_hash):
        pass

    def add_from_message(self, message):
        args = []
        for m in (
                'channel_id', 'parent', 'name', 'links', 'description',
                'links_add',
                'links_remove', 'temporary', 'position', 'description_hash'):
            args.append(getattr(message, m, None))
        self.add_channel(*args)
