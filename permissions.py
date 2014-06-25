import asyncio

from logbook import debug


__author__ = 'ankhmorporkian'


class Permission:
    def __init__(self, name):
        self.name = name


class Restrict:
    def __init__(self, permission):
        """
        If there are decorator arguments, the function
        to be decorated is not passed to the constructor!
        """
        self.perm = permission

    def __call__(self, f):
        debug("In __call__")
        if not asyncio.iscoroutine(f):
            f = asyncio.coroutine(f)

        @asyncio.coroutine
        def wrapped_f(s, source, *args, **kwargs):
            if self.perm.name in source.permissions:
                debug("Allowing")
                return (yield from f(s, source, *args, **kwargs))
            else:
                debug("Not allowed!")
                raise PermissionError(self.perm)
        wrapped_f.__doc__ = f.__doc__
        return wrapped_f

owner = Permission("owner")
admin = Permission("admin")
linker = Permission("linker")
grouper = Permission("grouper")
everyone = Permission("everyone")
all_perms = {x.name: x for x in [owner, admin, linker, grouper]}
