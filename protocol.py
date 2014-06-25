from construct import *

version = Struct("version",
                 Optional(UBInt32("version")),
                 Optional()
)