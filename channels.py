import logbook

from db import Channel, Session

logger = logbook.Logger("mumbleio.channel_manager")

class ChannelManager:
    def __init__(self):
        self.session = Session()

    def add_channel(self, id, parent=None, name=None, links=None,
                    description=None, links_add=None, links_remove=None,
                    temporary=None, position=None, description_hash=None):
        c = self.session.query(Channel).get(id)
        if c:
            logger.debug("Updating channel {} ({})".format(c.name, id))
            self.update_channel(id, parent_id=parent, name=name, description=description,
                                temporary=temporary, position=position, description_hash=description_hash)
        else:
            c = Channel(id=id,
                        parent_id=parent, name=name, links="",
                        description=description,
                        links_add="", links_remove="",
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
            logger.info("Deleted channel with ID {0}", id)
        except KeyError:
            logger.warning("Server removed channel with ID {}, "
                    "but we haven't seen it before!", id)
        except:
            pass

    def get_by_name(self, name) -> Channel:
        return self.session.query(Channel).filter_by(name=name).first()

    def get(self, id) -> Channel:
        if not isinstance(id, int):
            if not id.isdigit():
                id = self.get_by_name(id)
            else:
                id = int(id)
        return self.session.query(Channel).get(id)

    def get_like_name(self, name):
        return self.session.query(Channel).filter(Channel.name.like('%{}%'.format(name))).first()
    def update_channel(self, id, **kwargs):
        c = self.get(id)
        for key, value in kwargs.items():
            if value:
                setattr(c, key, value)

    def add_from_message(self, message):
        args = []
        for m in (
                'channel_id', 'parent', 'name', 'links', 'description',
                'links_add',
                'links_remove', 'temporary', 'position', 'description_hash'):
            args.append(getattr(message, m, None))
        self.add_channel(*args)
