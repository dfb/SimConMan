'''
acts as a bridge between FSForce for P3D and FFS

normal startup sequence:
- launch P3D, wait til we get to options screen
- start proxy.py
- start fsfloader.py

FlyInsideConnector
- mostly just a dispatcher
- fires input events, sim events
- maybe it queries connection handlers for their priority for a given event, they return None for don't send it, eh, also return whether they intend to mask it

ConnectionHandler
- in charge of translation to/from Simconnect names/values
- filters/translates events
- forwards simevents if client wants them
- translates input events to client mapped events if needed
- has a list of pending info on sim obj requests that it processes in tick. if not recurring, remove after sending

NEXT
- add ConnHandler.activeDataRequests
'''

import sys, socket, time, traceback, threading, json, struct
from simconnect import connection, message, defs as SC
import fsfloader

class Bag(dict):
    def __setattr__(self, k, v): self[k] = v

    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError('No such attribute %r' % k)

    def __delattr__(self, k):
        try: del self[k]
        except KeyError: raise AttributeError('No such attribute %r' % k)

    @staticmethod
    def FromJSON(j):
        return json.loads(j, object_pairs_hook=Bag)

    def ToJSON(self, indent=0):
        if indent > 0:
            return json.dumps(self, indent=indent, sort_keys=True)
        return json.dumps(self)

def log(*args):
    print(' '.join(str(x) for x in args))

def logTB():
    for line in traceback.format_exc().split('\n'):
        log(line)

class GV:
    keepRunning = True

class FlyInsideConnector:
    '''connects to and communicates with the FlyInside Flight Sim'''
    def __init__(self, recvPort, sendPort):
        self.scConnections = {} # handler ID -> ConnectionHandler (to SimConnect)0
        self.systemEventHandlers = {} # system event (e.g. 'SimStart') -> [list of (handlerID, client event num)]
        self.recvPort = recvPort
        self.sendPort = sendPort

        self.varToValues = {} # sim variable name to most recent value from sim
        self.outgoingMessages = []
        t = threading.Thread(target=self._MessagePump)
        t.daemon = 1
        t.start()

    def _MessagePump(self):
        '''sends and receives network messages to/from the flight sim'''
        recvSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recvSock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        recvSock.bind(('', self.recvPort))
        recvSock.settimeout(0.5)

        sendSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        destAddr = ('127.0.0.1', self.sendPort)

        idToVarNames = {} # string ID to sim variable name

        # on start, send a reset command so the sim will send us its var mapping and the initial state of everything
        needReset = True
        self.SimSend('RES:1')
        lastTick = 0.0
        try:
            while GV.keepRunning:
                try:
                    # Process incoming messages
                    msg, fromAddr = recvSock.recvfrom(4096)
                    msg = msg.decode('utf8')
                    if needReset:
                        if msg == 'RES:1':
                            needReset = False
                        else:
                            log('IGNORING:', msg)
                    else:
                        parts = msg.split(':')
                        if len(parts) != 2:
                            log('Malformed message:', parts)
                        else:
                            cmd, payload = parts
                            if cmd == 'DEF':
                                # Sim is defining a short ID for a variable name
                                varName, varID = payload.split('=')
                                idToVarNames[varID] = varName
                            elif cmd == 'VF':
                                # Sim is giving us an updated value for a float variable
                                varID, value = payload.split('=')
                                varName = idToVarNames[varID]
                                self.varToValues[varName] = float(value)
                            elif cmd == 'VS':
                                # Sim is giving us an updated value for a string variable
                                varID, value = payload.split('=')
                                varName = idToVarNames[varID]
                                self.varToValues[varName] = value
                            else:
                                log('Unhandled message:', cmd, payload)
                except socket.timeout:
                    pass

                # Process outgoing messages
                while self.outgoingMessages:
                    msg = self.outgoingMessages.pop(0)
                    sendSock.sendto(msg.encode('utf8'), destAddr)

                # Tick our connections
                now = time.time()
                if now - lastTick > 0.25:
                    self.Tick()
                    lastTick = time.time()
        finally:
            recvSock.close()

    def SimSend(self, msg):
        '''use this to send a message to the flight sim'''
        self.outgoingMessages.append(msg)

    def RegisterForSystemEvent(self, eventName, conn, clientEventNum):
        '''called by ConnectionHandlers to notify us that a SimConnect connection wants to receive a
        particular system event'''
        self.scConnections[conn.handlerID] = conn
        self.systemEventHandlers.setdefault(eventName, []).append((conn.handlerID, clientEventNum))

    def IsPaused(self):
        '''returns True if sim is paused'''
        return not not self.varToValues.get('SimState.Paused')

    def Tick(self):
        '''to be someday called periodically'''
        if not self.varToValues:
            return # startup, nothing to do yet
        for handlerID, conn in list(self.scConnections.items()):
            try:
                conn.Tick(self.varToValues)
            except:
                logTB()
                log('Failed to tick', handlerID, '- dropping the connection')
                del self.scConnections[handlerID]

    def FireEvent(self, eventName, **kwargs):
        '''dispatches a named sim event to all clients'''
        # TODO: we're supposed to fire the event in priority order to each client
        # TODO: clients can mask an event, preventing us from firing it to other clients (maybe let OnSimEvent return a value or raise an exception to stop firing?
        for handlerID, conn in self.scConnections.items()[:]:
            try:
                conn.OnSimEvent(eventName, **kwargs)
            except:
                logTB()
                log('Failed to deliver sim event', eventName, 'to', handlerID, '- dropping the connection')
                del self.scConnections[handlerID]

class PriorityGroup:
    '''a group of events at a certain priority (used for notification groups and input event mapping)'''
    def __init__(self, id):
        self.groupID = id
        self.priority = None # not sure what the default should be
        self.members = {} # member ID --> some sort of info object

class InputEventInfo:
    '''info about an input event mapping'''
    def __init__(self):
        self.downID = None
        self.downValue = None
        self.upID = None
        self.upValue = None
        self.maskable = False

ZEROS = bytearray(b'\x00' * 512)
def _VS(s, wide, maxLen):
    '''Used by ValueToBytes: returns bytes for the given string. Encodes to utf-8 if
    wide is False, else utf-16. Truncates to maxLen (in chars) and then padded to that
    length if needed.'''
    # TODO: verify maxLen for wide strings - is it bytes or chars for sure?
    # (for now I'm treating it like bytes)
    if wide:
        assert 0, 'Hrm, need to verify that utf-16 is right here, and whether or not the BOM should be included'
        s = s.encode('utf-16')
    else:
        s = s.encode('utf-8')
    ret = bytearray(s[:maxLen])
    padNeeded = maxLen - len(ret)
    if padNeeded > 0:
        ret.extend(ZEROS[:padNeeded])
    return ret

def ValueToBytes(v, dataType):
    '''Converts the given value into bytes based on the given SC.DATATYPE'''
    if dataType == SC.DATATYPE.INT32: return struct.pack('<i', dataType)
    if dataType == SC.DATATYPE.INT64: return struct.pack('<q', dataType)
    if dataType == SC.DATATYPE.FLOAT32: return struct.pack('<f', dataType)
    if dataType == SC.DATATYPE.FLOAT64: return struct.pack('<d', dataType)
    if dataType == SC.DATATYPE.STRING8: return _VS(v, False, 8)
    if dataType == SC.DATATYPE.STRING32: return _VS(v, False, 32)
    if dataType == SC.DATATYPE.STRING64: return _VS(v, False, 64)
    if dataType == SC.DATATYPE.STRING128: return _VS(v, False, 128)
    if dataType == SC.DATATYPE.STRING256: return _VS(v, False, 256)
    if dataType == SC.DATATYPE.STRING260: return _VS(v, False, 260)
    raise NotImplementedError('No support yet for data type %r' % dataType)

    # TODO: add support for the following
    # DATATYPE_STRINGV,        # variable-length narrow string
    # DATATYPE_INITPOSITION,   # see SIMCONNECT_DATA_INITPOSITION
    # DATATYPE_MARKERSTATE,    # see SIMCONNECT_DATA_MARKERSTATE
    # DATATYPE_WAYPOINT,       # see SIMCONNECT_DATA_WAYPOINT
    # DATATYPE_LATLONALT,      # see SIMCONNECT_DATA_LATLONALT
    # DATATYPE_XYZ,            # see SIMCONNECT_DATA_XYZ
    # DATATYPE_PBH,            # see SIMCONNECT_DATA_PBH
    # DATATYPE_OBSERVER,       # see SIMCONNECT_DATA_OBSERVER
    # DATATYPE_OBJECT_DAMAGED_BY_WEAPON,   # see SIMCONNECT_DATA_OBJECT_DAMAGED_BY_WEAPON
    # DATATYPE_VIDEO_STREAM_INFO,
    # DATATYPE_WSTRING8,       # 8 character wide string
    # DATATYPE_WSTRING32,      # 32 character wide string
    # DATATYPE_WSTRING64,      # 64 character wide string
    # DATATYPE_WSTRING128,     # 128 character wide string
    # DATATYPE_WSTRING256,     # 256 character wide string
    # DATATYPE_WSTRING260,     # 260 character wide string
    # DATATYPE_WSTRINGV) =range(28) # variable-length wide string

# Mapping from FSX variables to FFS variables. Each entry is
# fsx var name -> (ffs var name, ffs unit or None if no conversion is needed, default if missing)
FSX_FFS_MAP = {
    # Entries that have received at least cursory validation, or are ones we're stubbing out for now
    'title': ('Aircraft.Properties.Name', None, 'MyPlane'),
    'category': (None, None, 'Airplane'),
    'is slew active' : (None, None, False), # is slew active (vs flight model active)
    'airspeed true':('Aircraft.Position.Airspeed.True', 'meters per second', 0),
    'airspeed indicated':('Aircraft.Position.Airspeed.Indicated', 'meters per second', 0),
    'ground velocity':('Aircraft.Position.GroundSpeed.Value', 'meters per second', 0),
    'autopilot altitude lock' : (None, 'bool', False),
    'autopilot approach hold' : (None, 'bool', False),
    'autopilot attitude hold' : (None, 'bool', False),
    'autopilot backcourse hold' : (None, 'bool', False),
    'autopilot glideslope hold' : (None, 'bool', False),
    'autopilot heading lock' : (None, 'bool', False),
    'autopilot master' : (None, 'bool', False),
    'autopilot nav1 lock' : (None, 'bool', False),
    'autopilot vertical hold' : (None, 'bool', False),
    'sim on ground': ('Aircraft.Status.OnGround', 'bool', True),
    'stall alpha' : ('Aircraft.Properties.Dynamics.StallAlpha', 'radians', 0.26), # stall alpha, radians
    'pitot ice pct' : ('Aircraft.Status.PitotIce.Percent', '0..1', 0),
    'plane latitude' : ('Aircraft.Position.Latitude', 'degrees', 0), # N latitude, radians
    'plane longitude' : ('Aircraft.Position.Longitude', 'degrees', 0), # E longitude, radians
    'cable caught by tailhook' : (None, 'bool', False),
    'plane alt above ground' : ('Aircraft.Position.Altitude.Radar', 'meters', 0),
    'plane altitude' : ('Aircraft.Position.Altitude.True', 'meters', 0), # I'm not 100% sure this FSX var is true alt, but there are separate vars for AGL and indicated
    'center wheel rpm':('Aircraft.Wheel.Center.Rotation.RPM', 'rpm', 0),
    'velocity world y' : ('Aircraft.Position.VerticalSpeed.Value', 'meters per second', 0), # vertical speed, defaults to feet/sec
    'gear handle position' : ('Aircraft.Input.GearLever.Down', 'percent', True), # 1.0 if gear handle in "extended" pos, 0 if in retracted pos
    'general eng pct max rpm:1' : ('Aircraft.Engine.1.Piston.RPMPercent', 'percent', 50), # % of max rated RPM
    'general eng throttle lever position:1' : ('Aircraft.Controls.Engine.Throttle', 'percent', 50), # % of max throttle position, perc
    'turb eng afterburner:1' : (None, None, False), # afterburner state, bool
    'turb eng n1:1' : (None, None, 0), # turbine engine N1, perc
    'plane bank degrees' : ('Aircraft.Position.Bank.Value', 'radians', 0), # bank angle IN RADIANS by default. degrees banked to the left (negative = bank to the right)
    'elevator position' : ('Aircraft.Input.Pitch', 'percent', 0), # percent elevator input deflection - as a raw value, -1 (pushed in) to 1 (pulled out), or -100..100 as a percent - seems to be elevator *input* and not actual elevator angle
    'aileron left deflection pct' : ('Aircraft.Surfaces.Aileron.Left.Percent', 'percent', 0), # 0-1 (-100 = full left roll)
    'elevator trim position' : ('Aircraft.Surfaces.Elevator.Trim.Angle', 'radians', 0), # elevator trim deflection, radians
    'rotation velocity body x' : ('Aircraft.Velocity.Rotation.Local.X', 'radians per second', 0), # rot rate on X (pitch) axis (+=down, -=up), angular units/sec
    'rotation velocity body y' : ('Aircraft.Velocity.Rotation.Local.Y', 'radians per second', 0), # rot rate on Y (yaw) axis (+=CW, -=CCW), angular units/sec
    'rotation velocity body z' : ('Aircraft.Velocity.Rotation.Local.Z', 'radians per second', 0), # rot rate on Z (roll) axis (+=left, -=right), angular units/sec
    'aircraft wind y' : ('World.Wind.Velocity.Local.Y', 'meters per second', 5), # wind component in local vertical axis, knots
    'incidence alpha' : ('Aircraft.Dynamics.Alpha', 'radians', 0.1), # angle of attack, radians, remember that this doesn't change much since it's relative to the velocity vector

    # Appear to be missing from FFS
    # -- flight properties here --
    'stall warning' : (None, 'bool', False), # true if stall warning is on, bool
    'surface type' : (None, None, 4), # 1 = grass, 4=asphalt, 0=concrete, 3=grass bumpy, 5=short grass
    'gear center position' : (None, None, 0), # % center gear extended, 0..1
    'gear left position' : (None, None, 0), # % left gear extended, 0..1 (0=retracted)
    'gear right position' : (None, None, 0), # % right gear extended, 0..1

    # -- aircraft properties here --
    'is gear retractable' : (None, 'bool', True), # bool
    'visual model radius' : (None, None, 16.4), # model radius, meters
    'is tail dragger' : (None, 'bool', False), # bool
    'design speed vc' : (None, None, 20), # design speed at VC (cruising speed), feet/sec
    'design speed vs0' : (None, None, 20), # design speed at VS0 (stall speed in landing config), feet/sec
    'engine type' : (None, None, 0), # engine type: 0=piston, 1=jet, 2=none, 5=turboprop
}

OLD_MAP = {
    '':'Aircraft.Input.Roll',
    '':'SimState.Paused',
}

def ConvertValue(ffsName, ffsVal, ffsUnits, fsxUnits):
    '''Given a value from FlyInside and in the given units, convert it to the given FSX units'''
    ffsUnits = (ffsUnits or '').strip().lower()
    fsxUnits = (fsxUnits or '').strip().lower()
    if ffsUnits == fsxUnits:
        return ffsVal
    if ffsUnits == 'meters per second' and fsxUnits == 'knots':
        return ffsVal * 1.94384

    log('CONVERT:', ffsName, repr((ffsVal, ffsUnits, fsxUnits)))

class DataDefinitionEntry:
    '''one item of info a in a data definition'''
    def __init__(self, msg):
        self.fsxName = msg.datumName.lower()
        self.ffsName, self.ffsUnits, self.defaultValue = FSX_FFS_MAP[self.fsxName]
        self.units = msg.unitsName
        self.type = msg.dataType
        self.epsilon = msg.epsilon
        self.datumID = msg.datumID
        self.prevValue = None # for detecting when data has changed

    def ExtractValue(self, varValues):
        '''Extracts the current value from the given set of values, returning None if the value is not
        found. Converts the value (based on self.units) if needed before returning it.'''
        if not self.ffsName in varValues:
            return self.defaultValue
        ffsVal = varValues[self.ffsName]
        return ConvertValue(self.ffsName, ffsVal, self.ffsUnits, self.units)

    def HasChanged(self, extractedValue):
        '''Using a value from ExtractValue, returns True if the value has changed (taking into account
        self.epsilon if it makes sense'''
        if extractedValue is None:
            return False # I guess?
        if self.prevValue is None:
            return True
        # See if the value is different enough to count as a change
        if type(extractedValue) is int:
            changed = abs(extractedValue - self.prevValue) > int(self.epsilon) # doc says we truncate epsilon in this case
        elif type(extractedValue) is float:
            changed = abs(extractedValue - self.prevValue) > self.epsilon
        else:
            changed = extractedValue != self.prevValue
        return changed

    def GenValue(self, taggedFormat, force, varValues):
        '''Returns a binary blob for a SSimObjectData message. If taggedFormat is True, returns the value
        in tagged format (i.e. prefixed with the datumID). Updates self.prevValue before returning.'''
        cur = self.ExtractValue(varValues)
        if not force and not self.HasChanged(cur):
            return None

        self.prevValue = cur
        ret = bytearray()
        if taggedFormat:
            # Tagged format is datumID (as a 4B value) + data
            ret.extend(struct.pack('<L', self.datumID))
        ret.extend(ValueToBytes(cur, self.type))
        return ret

class ObjectDataRequest:
    def __init__(self, msg):
        # warn on not implemented stuff that is probably ok
        if msg.origin != 0: log('WARNING: ignoring origin in', msg)
        if msg.limit != 0: log('WARNING: ignoring limit in', msg)
        if msg.interval != 0: log('WARNING: ignoring interval in', msg)
        self.requestID = msg.requestID
        self.objectID = msg.objectID
        self.definitionID = msg.definitionID
        self.period = msg.period
        self.flags = msg.flags
        self.taggedFormat = not not (msg.flags & SC.DATA_REQUEST_FLAG.TAGGED) # return values in tagged format?
        self.onlyWhenChanged = not not (msg.flags & SC.DATA_REQUEST_FLAG.CHANGED) # send always or only if it changed?
        self.lastSent = None # timestamp of when we last fulfilled the request

    def Due(self):
        '''Returns True if it's time to send data for this request again'''
        if self.period == SC.PERIOD.NEVER:
            return False # does this ever happen?
        if self.lastSent is None:
            return True
        if self.period == SC.PERIOD.SECOND:
            return time.time() - self.lastSent >= 1.0
        return True

    def GenMessage(self, varValues, dataDefEntries):
        '''Creates a message to send to the client with the requested data. Returns (msg, finished), where
        finished is True if this data request is done and can be erased from the list of active data requests.
        varValues is a mapping of the most recent sim variable values and dataDefEntries is a list of DataDefinitionEntry
        objects. Returns None if '''
        self.lastSent = time.time()
        finished = (self.period in (SC.PERIOD.NEVER, SC.PERIOD.ONCE)) # TODO: add support for limit
        entries = []

        # There is some complexity around what we return. We've already checked self.Due() by now, so rules around
        # when to apply stuff have already been applied for the most part, but if self.onlyWhenChanged is set, then
        # we send only the values that have changed. Except that if the data isn't being sent back in tagged format, then
        # if self.onlyWhenChanged is set and at least one entry has changed, then we send them all back.
        if self.onlyWhenChanged and not self.taggedFormat:
            # The special case: we're not using tagged format, so it's all or nothing, so we send them all back if
            # at least one entry changed, otherwise we send back nothing. So first check to see if any changed.
            anyChanged = False
            for dde in dataDefEntries:
                cur = dde.ExtractValue(varValues)
                if dde.HasChanged(cur):
                    anyChanged = True
                    break

            # If any changed, make them all generate new values
            if anyChanged:
                for dde in dataDefEntries:
                    entry = dde.GenValue(False, True, varValues)
                    if entry is not None:
                        entries.append(entry)
        else:
            for dde in dataDefEntries:
                entry = dde.GenValue(self.taggedFormat, not self.onlyWhenChanged, varValues)
                if entry is not None:
                    entries.append(entry)

        if not entries:
            return None, finished

        msg = message.SSimObjectData(requestID=self.requestID, objectID=self.objectID, definitionID=self.definitionID,
                                     entryNumber=1, outOf=1, flags=self.flags)
        msg.data = b''.join(entries)
        msg.defineCount = len(msg.data) // 8 # docs say "number of 8-byte elements in the dwData array"
        return msg, finished

class ConnectionHandler:
    nextID = 0
    @staticmethod
    def Create(sock, fic):
        c = ConnectionHandler(sock, fic)
        t = threading.Thread(target=c.Handle)
        t.daemon = True
        t.start()
        return c

    def __init__(self, sock, fic):
        self.handlerID = ConnectionHandler.nextID
        ConnectionHandler.nextID += 1
        self.client = connection.ClientConnection(sock)
        self.fic = fic
        self.protocol = -1
        self.dataDefs = {} # def ID --> [ items ]
        self.simEventMap = {} # sim event name --> client event ID
        self.notificationGroups = {} # client notification group ID -> PriorityGroup instance
        self.inputGroups = {} # client mapped input event group -> PrioritGroup instance
        self.activeDataRequests = [] # pending (and possibly repeating) requests from the sim for data

    def Handle(self):
        try:
            while GV.keepRunning:
                didWork = False

                # Grab and dispatch messages from FSForce
                msg = self.client.Recv()
                if msg is not None:
                    didWork = True
                    handlerName = 'On' + msg.__class__.__name__
                    handler = getattr(self, handlerName, None)
                    if handler is None:
                        log('ERROR: no handler for', handlerName)
                        log('[%s]' % self.handlerID, msg)
                        continue
                    self.protocol = msg._protocol # really needed only once
                    handler(msg)

                # don't spin
                if not didWork:
                    time.sleep(0.05)
        except connection.Closed as e:
            log('Connection closed', e)

    def Send(self, msg):
        '''used by other methods to send a message to the client, setting the _protocol
        member of the message first'''
        msg._protocol = self.protocol
        #log('SENDING TO SIM:', msg)
        self.client.Send(msg)

    def Tick(self, varValues):
        '''called periodically to see if we need to send any new messages to the client. varValues is a dict
        of simVarName -> most recent value'''
        keep = []
        toDelete = []
        for dr in self.activeDataRequests:
            if not dr.Due():
                continue

            dataDefEntries = self.dataDefs.get(dr.definitionID)
            if not dataDefEntries:
                log('ERROR: no data def entries for dataDefinitionID', dr.id)
                continue

            msg, finished = dr.GenMessage(varValues, dataDefEntries)
            if finished:
                toDelete.append(dr)
            if msg is not None:
                self.Send(msg)

        # Remove any data requests that are now completely fulfilled
        for dr in toDelete:
            self.activeDataRequests.remove(dr)

    def OnCOpen(self, msg):
        resp = message.SOpen()
        resp.appName = 'Lockheed Martin® Prepar3D® v4'
        resp.appVer = [4,3]
        resp.appBuild = [29, 25520]
        resp.scVer = [4, 3]
        resp.scBuild = [0, 0]
        resp._ignore = 5 # in P3D seems to be something like "connections left"?
        resp._ignore2 = 0
        self.Send(resp)

    def OnCSubscribeToSystemEvent(self, msg):
        # TODO: have fic always send this to us, and then we decide whether or not to send to the client
        self.fic.RegisterForSystemEvent(msg.eventName, self, msg.clientEventID)

    def OnCRequestJoystickDeviceInfo(self, msg):
        resp = message.SJoystickDeviceInfo()
        resp.requestID = msg.requestID
        resp.count = 2
        # TODO: implement this for reals
        resp.joysticks = [
            message.JoystickDeviceInfo(name='Saitek Pro Flight Rudder Pedals', number=0),
            message.JoystickDeviceInfo(name='Iris Dynamics Yoke', number=1),
        ]
        self.Send(resp)

    def OnCRequestSystemState(self, msg):
        resp = message.SSystemState(requestID=msg.requestID, dataInteger=0, dataFloat=0.0, dataString='')
        if msg.stateName == 'Sim':
            resp.dataInteger = 0 if self.fic.IsPaused() else 1
            self.Send(resp)
        else:
            # TODO: handle other cases
            log('ERROR: unhandled system state request', msg)

    def OnCAddToDataDefinition(self, msg):
        self.dataDefs.setdefault(msg.dataDefinitionID, []).append(DataDefinitionEntry(msg))

    def OnCMapClientEventToSimEvent(self, msg):
        # TODO: make sure we handle all desired sim events
        self.simEventMap[msg.eventName] = msg.eventID

    def GetNotificationGroup(self, groupID):
        g = self.notificationGroups.get(id)
        if g is None:
            g = PriorityGroup(id)
            self.notificationGroups[id] = g
        return g

    def GetInputGroup(self, groupID):
        g = self.inputGroups.get(id)
        if g is None:
            g = PriorityGroup(id)
            g.enabled = False
            self.inputGroups[id] = g
        return g

    def OnCAddClientEventToNotificationGroup(self, msg):
        g = self.GetNotificationGroup(msg.groupID)
        g.members[msg.eventID] = msg.maskable # right now all we store is whether or not it's maskable

    def OnCSetNotificationGroupPriority(self, msg):
        g = self.GetNotificationGroup(msg.groupID)
        g.priority = msg.priority

    def OnCMapInputEventToClientEvent(self, msg):
        g = self.GetInputGroup(msg.groupID)
        # TODO: make sure fic fires desired input events
        m = InputEventInfo()
        m.downID = msg.downID
        m.downValue = msg.downValue
        m.upID = msg.upID
        m.upValue = msg.upValue
        m.maskable = msg.maskable
        g.members[msg.definition] = m

    def OnCSetInputGroupState(self, msg):
        g = self.GetInputGroup(msg.groupID)
        g.enabled = (msg.state != 0)
        # TODO: make sure we honor enabled when firing events

    def OnCSetInputGroupPriority(self, msg):
        g = self.GetInputGroup(msg.groupID)
        g.priority = msg.priority
        # TODO: make sure we follow the priority rules

    def OnCRequestDataOnSimObject(self, msg):
        if msg.objectID != SC.OBJECT_ID_USER:
            log('WARNING: not handling', msg)
            return
        self.activeDataRequests.append(ObjectDataRequest(msg))

    def OnCTransmitClientEvent(self, msg):
        pass
        # TODO: follow all the simconnect doc rules

def FSForceListener(port, fic):
    '''creates a dummy simconnect server to handle messages from FSForce, then loads FSForce
    in the background'''
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', port))
    sock.listen(10)
    sock.setblocking(0)
    log('FSForceListener listening on port', port)

    # Now that the server sock is ready, we can fire up FSForce
    runner = fsfloader.FSForceRunner()
    runner.Start()

    while 1:
        try:
            q,v = sock.accept()
            log('Accepting connection')
            ConnectionHandler.Create(q, fic)
        except BlockingIOError:
            try:
                time.sleep(0.25)
            except KeyboardInterrupt:
                break
        except KeyboardInterrupt:
            break
        except:
            logTB()
    log('FSForceListener shutting down')
    GV.keepRunning = False
    sock.close()
    runner.Stop()

if __name__ == '__main__':
    fic = FlyInsideConnector(61000, 62000)
    FSForceListener(10000, fic)

