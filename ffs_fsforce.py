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

import sys, socket, time, traceback, threading, json
from simconnect import connection, message
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
                            elif cmd == 'V':
                                # Sim is giving us an updated value for a variable
                                varID, value = payload.split('=')
                                varName = idToVarNames[varID]
                                self.varToValues[varName] = float(value)
                                # TODO: string vars and whatnot
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

    def UserInUI(self):
        '''returns True if the user is doing stuff in the UI, False if they are flying the aircraft'''
        return False # It looks like FFS is never "in UI" - it can be paused but doesn't have a separate "in ui" state

    def Tick(self):
        '''to be someday called periodically'''
        if not self.varToValues:
            return # startup, nothing to do yet
        for handlerID, conn in list(self.scConnections.items()):
            try:
                conn.Tick(self.varToValues)
            except:
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
        self.client.Send(msg)

    def Tick(self, varValues):
        '''called periodically to see if we need to send any new messages to the client. varValues is a dict
        of simVarName -> most recent value'''
        # TODO: check for subscribed data changes and send them
        log(varValues)

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
            resp.dataInteger = 0 if self.fic.UserInUI() else 1
            self.Send(resp)
        else:
            # TODO: handle other cases
            log('ERROR: unhandled system state request', msg)

    def OnCAddToDataDefinition(self, msg):
        d = Bag(name=msg.datumName, units=msg.unitsName, type=msg.dataType, epsilon=msg.epsilon, id=msg.datumID)
        log('data def:', msg.dataDefinitionID, d)
        self.dataDefs.setdefault(msg.dataDefinitionID, []).append(d)

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
        log(msg)
        # ReqDataOnSimObject <CRequestDataOnSimObject: requestID: 1, definitionID: 1, objectID: 0, period: 3, flags: 1, origin: 0, interval: 0, limit: 0>
        # ReqDataOnSimObject <CRequestDataOnSimObject: requestID: 2, definitionID: 2, objectID: 0, period: 3, flags: 1, origin: 0, interval: 0, limit: 0>
        # TODO: implement

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

