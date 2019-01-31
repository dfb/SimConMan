'''
Defines stuff from SimConnect.h
Tries to follow the header fairly closely (except for dropping the 'SIMCONNECT_' prefix from everything)
'''

OBJECT_ID_USER = 0

class PERIOD:
    '''Object Data Request Period values'''
    NEVER, ONCE, VISUAL_FRAME, SIM_FRAME, SECOND = range(5)

class DATA_REQUEST_FLAG:
    DEFAULT = 0x00000000
    CHANGED = 0x00000001 # send requested data when value(s) change
    TAGGED  = 0x00000002 # send requested data in tagged format
    BLOCK   = 0x00000004 # Block server when data is sent

class DATATYPE:
    (
    INVALID,                 # invalid data type

    INT32,          # 32-bit integer number
    INT64,          # 64-bit integer number
    FLOAT32,        # 32-bit floating-point number (float)
    FLOAT64,        # 64-bit floating-point number (double)

    STRING8,        # 8 character narrow string
    STRING32,       # 32 character narrow string
    STRING64,       # 64 character narrow string
    STRING128,      # 128 character narrow string
    STRING256,      # 256 character narrow string
    STRING260,      # 260 character narrow string
    STRINGV,        # variable-length narrow string

    INITPOSITION,   # see SIMCONNECT_DATA_INITPOSITION
    MARKERSTATE,    # see SIMCONNECT_DATA_MARKERSTATE
    WAYPOINT,       # see SIMCONNECT_DATA_WAYPOINT
    LATLONALT,      # see SIMCONNECT_DATA_LATLONALT
    XYZ,            # see SIMCONNECT_DATA_XYZ
    PBH,            # see SIMCONNECT_DATA_PBH
    OBSERVER,       # see SIMCONNECT_DATA_OBSERVER
    OBJECT_DAMAGED_BY_WEAPON,   # see SIMCONNECT_DATA_OBJECT_DAMAGED_BY_WEAPON
    VIDEO_STREAM_INFO,

    WSTRING8,       # 8 character wide string
    WSTRING32,      # 32 character wide string
    WSTRING64,      # 64 character wide string
    WSTRING128,     # 128 character wide string
    WSTRING256,     # 256 character wide string
    WSTRING260,     # 260 character wide string
    WSTRINGV) =range(28) # variable-length wide string



