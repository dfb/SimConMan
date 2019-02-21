'''
Connects to P3D as a SimConnect client and requests data/events so we can verify the format, units, and
values in a data stream.
'''

from simconnect.utils import *
import sys, socket, time, threading, struct
from simconnect import connection, message as M, defs as SC

class GV:
    keepRunning = True
    counter = 0 # message counter
    server = None # server socket
    dataDefEntries = []
    clientEventEntries = []

def OnSOpen(msg): log(msg)
def OnSSystemState(msg): log(msg)

def OnSSimObjectData(msg):
    data = msg.data
    ret = []
    for entry in GV.dataDefEntries:
        ret.append(entry.Decode(data))
    log(ret)

def OnSEvent(msg):
    handled = False
    for entry in GV.clientEventEntries:
        if msg.eventID == entry.eventID:
            log('Event', entry.eventName, msg.data, msg.flags)
            handled = True
            break

    if not handled:
        log('UNHANDLED:', msg)

def Send(msg):
    msg._protocol = 29
    msg._counter = GV.counter
    GV.counter += 1
    GV.server.Send(msg)
    #log('sent', msg._counter, msg)

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

class ClientEventEntry:
    '''cheating: used for both MapClientEventToSimEvent and MapInputEventToClientEvent since our use cases so far are simple enough
    that the two are effectively the same'''
    def __init__(self, eventName, eventID, isInputEvent):
        self.eventName = eventName
        self.eventID = eventID
        if isInputEvent:
            Send(M.CMapClientEventToSimEvent(eventID=eventID, eventName=''))
            Send(M.CAddClientEventToNotificationGroup(groupID=1, eventID=eventID, maskable=0))
            Send(M.CMapInputEventToClientEvent(groupID=1, definition=eventName, downID=eventID, downValue=0, upID=4294967295, upValue=0, maskable=1))
        else:
            Send(M.CMapClientEventToSimEvent(eventID=eventID, eventName=eventName))
            Send(M.CAddClientEventToNotificationGroup(groupID=1, eventID=eventID, maskable=0))

def RunClient(simPort):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', simPort))
    GV.server = connection.ServerConnection(sock)

    Send(M.COpen(appName='P3DLogger', _ignore=0, _ignore2=0, simID='D3P', version=[4,3], build=[0,0]))
    Send(M.CRequestSystemState(requestID=0, stateName='Sim'))
    Send(M.CSubscribeToSystemEvent(clientEventID=3, eventName='SimStart'))

    DDE = DataDefEntry
    GV.dataDefEntries = [ # just uncomment the ones you want to see
        #DataDefEntry('AILERON LEFT DEFLECTION PCT', 'Percent', 3, 1.0),
        #DataDefEntry('AIRCRAFT WIND Y', 'knots', 3, 0.10000000149011612),
        #DataDefEntry('AUTOPILOT ALTITUDE LOCK', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT APPROACH HOLD', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT ATTITUDE HOLD', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT BACKCOURSE HOLD', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT GLIDESLOPE HOLD', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT HEADING LOCK', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT MASTER', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT NAV1 LOCK', 'Bool', 3, 0.0),
        #DataDefEntry('AUTOPILOT VERTICAL HOLD', 'Bool', 3, 0.0),
        #DataDefEntry('Airspeed Indicated', 'knots', 3, 1.0),
        #DataDefEntry('Airspeed True', 'knots', 3, 1.0),
        #DataDefEntry('CABLE CAUGHT BY TAILHOOK', 'Number', 3, 0.0),
        #DataDefEntry('CENTER WHEEL RPM', 'RPM', 3, 80.0),
        #DataDefEntry('DESIGN SPEED VC', 'knots', 3, 0.0),
        #DataDefEntry('DESIGN SPEED VS0', 'knots', 3, 0.0),
        #DataDefEntry('ELEVATOR POSITION', 'Percent', 3, 0.5),
        #DataDefEntry('ELEVATOR TRIM POSITION', 'Degrees', 3, 0.10000000149011612),
        #DataDefEntry('ELEVATOR TRIM POSITION', 'Degrees', 4, 0.0),
        #DataDefEntry('ENGINE TYPE', 'ENUM', 3, 0.0),
        #DataDefEntry('GENERAL ENG PCT MAX RPM:1', 'Percent', 3, 2.0),
        #DataDefEntry('GENERAL ENG THROTTLE LEVER POSITION:1', 'Percent', 3, 4.0),
        #DataDefEntry('Gear Center Position', 'Percent', 3, 0.0),
        #DataDefEntry('Gear Handle Position', 'Bool', 3, 0.0),
        #DataDefEntry('Gear Left Position', 'Percent', 3, 0.0),
        #DataDefEntry('Gear Right Position', 'Percent', 3, 0.0),
        #DataDefEntry('Ground Velocity', 'Knots', 3, 0.20000000298023224),
        #DataDefEntry('INCIDENCE ALPHA', 'Degrees', 3, 0.10000000149011612),
        #DataDefEntry('IS TAIL DRAGGER', 'Bool', 3, 0.0),
        #DataDefEntry('Is Gear Retractable', 'Bool', 3, 0.0),
        #DataDefEntry('Is Slew Active', 'Bool', 3, 0.0),
        #DataDefEntry('PLANE ALT ABOVE GROUND', 'feet', 3, 30.0),
        #DataDefEntry('PLANE BANK DEGREES', 'Degrees', 3, 1.0),
        #DataDefEntry('Pitot Ice Pct', 'Percent over 100', 3, 0.009999999776482582),
        #DataDefEntry('Plane Altitude', 'feet', 3, 30.0),
        #DataDefEntry('Plane Latitude', 'degrees', 3, 0.008299999870359898),
        #DataDefEntry('Plane Longitude', 'degrees', 3, 0.008299999870359898),
        #DataDefEntry('STALL ALPHA', 'Degrees', 3, 0.0),
        #DataDefEntry('STALL WARNING', 'Bool', 3, 0.0),
        #DataDefEntry('Sim On Ground', 'Bool', 3, 0.0),
        #DataDefEntry('Surface Type', 'Enum', 3, 0.0),
        #DataDefEntry('TURB ENG AFTERBURNER:1', 'Bool', 3, 0.0),
        #DataDefEntry('TURB ENG N1:1', 'Percent', 3, 1.0),
        #DataDefEntry('VELOCITY WORLD Y', 'Feet Per Minute', 3, 10.0),
        #DataDefEntry('Visual Model Radius', 'Feet', 3, 0.0),
        #DataDefEntry('ROTATION VELOCITY BODY X', 'degrees per second', 3, 0.5),
        #DataDefEntry('ROTATION VELOCITY BODY Y', 'Degrees per second', 3, 0.5),
        DataDefEntry('ROTATION VELOCITY BODY Z', 'Degrees per second', 3, 0.5),
    ]
    if GV.dataDefEntries:
        Send(M.CRequestDataOnSimObject(requestID=1, definitionID=1, objectID=0, period=3, flags=1, origin=0, interval=0, limit=0))

    Send(M.CMapClientEventToSimEvent(eventID=12, eventName='FSF.STOP_EFFECTS'))
    Send(M.CAddClientEventToNotificationGroup(groupID=5, eventID=12, maskable=0))
    Send(M.CSetNotificationGroupPriority(groupID=5, priority=1))

    GV.clientEventEntries = [
        # Input events
        #ClientEventEntry('Shift+9', 35, True), # arbitrary mapping as a way for an unhandled keypress to result in an event firing to the client
        ClientEventEntry('Shift+0', 36, True),
        #ClientEventEntry('Joystick:1:YAxis', 59, True), # -32k=pushed in, 32k=pulled out
        #ClientEventEntry('Joystick:1:XAxis', 62, True), # -32k=left, 32k=right

        # Sim events
        ClientEventEntry('AXIS_LEFT_BRAKE_SET', 52, False), # -16384=no brakes, 16384=max brakes
        ClientEventEntry('AXIS_RIGHT_BRAKE_SET', 53, False), # -16384=no brakes, 16384=max brakes
        #ClientEventEntry('AXIS_ELEVATOR_SET', 60, False), # -16384=full up, 16384=full down
        #ClientEventEntry('AP_ATT_HOLD', 63, False), # autopilot att hold
        #ClientEventEntry('AXIS_AILERONS_SET', 61, False), # -16384=full right, 16384=full left
        #ClientEventEntry('TAKEOFF_ASSIST_FIRE', 25, False), # catapult fire
    ]

    if GV.clientEventEntries:
        Send(M.CSetInputGroupState(groupID=1, state=1))
        Send(M.CSetInputGroupPriority(groupID=1, priority=1))

    # Note so I don't forget: when mapping client events to sim events:
    # - if a period is in the event name, it's a custom event that all clients can subscribe to
    #   (so a client will say to server, "for me, event Foo.Bar has ID 2" and another client will say, "for me, event Foo.Bar has ID 7",
    #    and then later the first client will say, "TransmitClientEvent(2)" and the other client will receive event 7)
    # - if event name is empty, it's a private event (so far I've only seen it used for a subsequent call to MapInputEventToClientEvent)
    # - otherwise, it should be a standard FSX event

    while 1:
        didWork = False
        msg = GV.server.Recv()
        if msg is not None:
            didWork = True
            handler = globals().get('On' + msg.__class__.__name__)
            if handler is None:
                log('ERROR: no handler for', msg)
            else:
                msgs = handler(msg)
                if msgs:
                    for m in msgs:
                        Send(m)

        if not didWork:
            time.sleep(0.1)

if __name__ == '__main__':
    simPort = 12500
    RunClient(simPort)

