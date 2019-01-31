'''
Connects to P3D as a SimConnect client and requests dataso we can verify the format, units, and
values in a data stream.
'''

import sys, socket, time, traceback, threading, struct
from simconnect import connection, message as M, defs as SC

def log(*args): print(' '.join(str(x) for x in args))
def logTB():
    for line in traceback.format_exc().split('\n'):
        log(line)

class GV:
    keepRunning = True
    counter = 0 # message counter
    server = None # server socket
    entries = [] # list of data def entries

def OnSOpen(msg):
    log(msg)

def OnSSimObjectData(msg):
    data = msg.data
    ret = []
    for entry in GV.entries:
        ret.append(entry.Decode(data))
    log(ret)

def Send(msg):
    msg._protocol = 29
    msg._counter = GV.counter
    GV.counter += 1
    GV.server.Send(msg)

class DataDefEntry:
    def __init__(self, varName, unitsName, dataType, epsilon=0.0):
        self.varName = varName
        self.unitsName = unitsName
        self.dataType = dataType
        self.epsilon = epsilon
        Send(M.CAddToDataDefinition(dataDefinitionID=1, datumName=varName, unitsName=unitsName, dataType=dataType, epsilon=epsilon, datumID=4294967295))

    def Decode(self, data):
        '''decodes this entry from a server response message. Returns (varName, value)'''
        if self.dataType == SC.DATATYPE.FLOAT32:
            value = struct.unpack('<f', data[:4])[0]
            data[:] = data[4:]
        elif self.dataType == SC.DATATYPE.FLOAT64:
            value = struct.unpack('<d', data[:8])[0]
            data[:] = data[8:]
        else:
            raise NotImplementedError('Cannot handle data type %r' % self.dataType)
        return (self.varName, value)

def RunClient(simPort):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', simPort))
    GV.server = connection.ServerConnection(sock)

    Send(M.COpen(appName='P3DLogger', _ignore=0, _ignore2=0, simID='D3P', version=[4,3], build=[0,0]))
    DDE = DataDefEntry
    GV.entries = [ # just uncomment the ones you want to see
        #DataDefEntry('Airspeed Indicated', 'knots', 3, 1.0),
        #DataDefEntry('Airspeed True', 'knots', 3, 1.0),
        #DataDefEntry('Is Slew Active', 'Bool', 3, 0.0),
        #DataDefEntry('Pitot Ice Pct', 'Percent over 100', 3, 0.009999999776482582),
        #DataDefEntry('Plane Altitude', 'feet', 3, 30.0),
        #DataDefEntry('PLANE ALT ABOVE GROUND', 'feet', 3, 30.0),
        #DataDefEntry('Plane Latitude', 'degrees', 3, 0.008299999870359898),
        #DataDefEntry('Plane Longitude', 'degrees', 3, 0.008299999870359898),
        #DataDefEntry('Surface Type', 'Enum', 3, 0.0),
        #DataDefEntry('Sim On Ground', 'Bool', 3, 0.0),
        #DataDefEntry('Gear Handle Position', 'Bool', 3, 0.0),
        #DataDefEntry('Is Gear Retractable', 'Bool', 3, 0.0),
        #DataDefEntry('Gear Right Position', 'Percent', 3, 0.0),
        #DataDefEntry('Gear Left Position', 'Percent', 3, 0.0),
        #DataDefEntry('Gear Center Position', 'Percent', 3, 0.0),
        #DataDefEntry('AUTOPILOT MASTER', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT APPROACH HOLD', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT ALTITUDE LOCK', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT ATTITUDE HOLD', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT GLIDESLOPE HOLD', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT BACKCOURSE HOLD', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT VERTICAL HOLD', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT NAV1 LOCK', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT HEADING LOCK', 'Bool', 3, 0.0),
        #DataDefEntry('ELEVATOR TRIM POSITION', 'Degrees', 3, 0.10000000149011612),
        #DataDefEntry('ROTATION VELOCITY BODY X', 'degrees per second', 3, 0.5),
        #DataDefEntry('CENTER WHEEL RPM', 'RPM', 3, 80.0),
        #DataDefEntry('Visual Model Radius', 'Feet', 3, 0.0),
        #DataDefEntry('DESIGN SPEED VS0', 'knots', 3, 0.0),
        #DataDefEntry('DESIGN SPEED VC', 'knots', 3, 0.0),
        #DataDefEntry('IS TAIL DRAGGER', 'Bool', 3, 0.0),
        #DataDefEntry('ENGINE TYPE', 'ENUM', 3, 0.0),
        #DataDefEntry('ROTATION VELOCITY BODY Y', 'Degrees per second', 3, 0.5),
        #DataDefEntry('GENERAL ENG THROTTLE LEVER POSITION:1', 'Percent', 3, 4.0),
        #DataDefEntry('TURB ENG N1:1', 'Percent', 3, 1.0),
        #DataDefEntry('GENERAL ENG PCT MAX RPM:1', 'Percent', 3, 2.0),
        #DataDefEntry('INCIDENCE ALPHA', 'Degrees', 3, 0.10000000149011612),
        #DataDefEntry('STALL ALPHA', 'Degrees', 3, 0.0),
        #DataDefEntry('STALL WARNING', 'Bool', 3, 0.0),
        #DataDefEntry('TURB ENG AFTERBURNER:1', 'Bool', 3, 0.0),
        #DataDefEntry('CABLE CAUGHT BY TAILHOOK', 'Number', 3, 0.0),
        #DataDefEntry('AIRCRAFT WIND Y', 'knots', 3, 0.10000000149011612),
        #DataDefEntry('AILERON LEFT DEFLECTION PCT', 'Percent', 3, 1.0),
        #DataDefEntry('Ground Velocity', 'Knots', 3, 0.20000000298023224),
        #DataDefEntry('VELOCITY WORLD Y', 'Feet Per Minute', 3, 10.0),
        #DataDefEntry('PLANE BANK DEGREES', 'Degrees', 3, 1.0),
        #DataDefEntry('ELEVATOR TRIM POSITION', 'Degrees', 4, 0.0),
        #DataDefEntry('ELEVATOR POSITION', 'Percent', 3, 0.5),
    ]
    Send(M.CRequestDataOnSimObject(requestID=1, definitionID=1, objectID=0, period=3, flags=1, origin=0, interval=0, limit=0))
    while 1:
        didWork = False
        msg = GV.server.Recv()
        if msg is not None:
            didWork = True
            handler = globals().get('On' + msg.__class__.__name__)
            if handler is None:
                print('ERROR: no handler for', msg)
            else:
                msgs = handler(msg)
                if msgs:
                    for m in msgs:
                        Send(m)

        if didWork:
            time.sleep(0.1)

if __name__ == '__main__':
    simPort = 12500
    RunClient(simPort)

