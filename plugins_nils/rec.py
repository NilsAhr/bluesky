#first plugin to log and record data

""" BlueSky deletion area plugin. This plugin can use an area definition to
    delete aircraft that exit the area. Statistics on these flights can be
    logged with the FLSTLOG logger. """
import numpy as np
# Import the global bluesky objects. Uncomment the ones you need
from bluesky import sim, traf  #, settings, navdb, traf, sim, scr, tools
from bluesky.tools import datalog, areafilter
from bluesky.core import Entity, timed_function
from bluesky.tools.aero import ft,kts,nm,fpm

from bluesky import stack
import bluesky as bs

# Log parameters for the flight statistics log
flstheader = \
    '#######################################################\n' + \
    'FLST LOG\n' + \
    'Flight Statistics\n' + \
    '#######################################################\n\n' + \
    'Parameters [Units]:\n' + \
    'Deletion Time [s], ' + \
    'Call sign [-], ' + \
    'Spawn Time [s], ' + \
    'Flight time [s], ' + \
    'Actual Distance 2D [nm], ' + \
    'Actual Distance 3D [nm], ' + \
    'Actual Altitude 2D [ft], ' + \
    'Work Done [MJ], ' + \
    'Latitude [deg], ' + \
    'Longitude [deg], ' + \
    'Altitude [ft], ' + \
    'TAS [kts], ' + \
    'Vertical Speed [fpm], ' + \
    'Heading [deg], ' + \
    'Origin Lat [deg], ' + \
    'Origin Lon [deg], ' + \
    'Destination Lat [deg], ' + \
    'Destination Lon [deg], ' + \
    'ASAS Active [bool], ' + \
    'Pilot ALT [ft], ' + \
    'Pilot SPD (TAS) [kts], ' + \
    'Pilot HDG [deg], ' + \
    'Pilot VS [fpm]'  + '\n'

confheader = \
    '#######################################################\n' + \
    'CONF LOG\n' + \
    'Conflict Statistics\n' + \
    '#######################################################\n\n' + \
    'Parameters [Units]:\n' + \
    'Simulation time [s], ' + \
    'ACID1 [-],' + \
    'ACID2 [-],' + \
    'LAT1 [deg],' + \
    'LON1 [deg],' + \
    'ALT1 [ft],' + \
    'LAT2 [deg],' + \
    'LON2 [deg],' + \
    'ALT2 [ft],' + \
    'CPALAT [lat],' + \
    'CPALON [lon]\n'

# Global data
rec = None

### Initialization function of your plugin. Do not change the name of this
### function, as it is the way BlueSky recognises this file as a plugin.
def init_plugin():

    # Addtional initilisation code
    global rec
    rec = Rec()

    # Configuration parameters
    config = {
        # The name of your plugin
        'plugin_name':     'Rec',

        # The type of this plugin. For now, only simulation plugins are possible.
        'plugin_type':     'sim',

        'update':   rec.update      
        }

    # init_plugin() should always return these two dicts.
    return config

class Rec(Entity):
    ''' Recoder for flight status and conflict parameters | Traffic area: delete traffic when it leaves this area (so not when outside)'''
    def __init__(self):
        super().__init__()
        # Parameters of area
        #self.active = False
        self.delarea = ''
        self.exparea = ''
        self.swtaxi = True  # Default ON: Doesn't do anything. See comments of set_taxi function below.
        self.swtaxialt = 1500.0  # Default alt for TAXI OFF
        self.prevconfpairs = set()
        self.confinside_all = 0

        # The FLST logger
        #(name, dt, flstheader)
        self.flstlog = datalog.crelog('FLSTLOG', None, flstheader)
        self.conflog = datalog.crelog('CONFLOG', None, confheader)

        #most important bluesky traffic arrays ()
        with self.settrafarrays():
            self.insdel = np.array([], dtype=bool) # In deletion area or not
            self.insexp = np.array([], dtype=bool) # In experiment area or not
            self.oldalt = np.array([], dtype=float)
            self.distance2D = np.array([], dtype=float)
            self.distance3D = np.array([], dtype=float)
            self.altitude2D = np.array([], dtype=float)
            self.dstart2D = np.array([])
            self.dstart3D = np.array([])
            self.workstart = np.array([])
            self.entrytime = np.array([], dtype=float)
            self.create_time = np.array([], dtype=float)

    def reset(self):
        ''' Reset area state when simulation is reset. '''
        super().reset()
        #self.active = False
        self.delarea = ''
        self.exparea = ''
        self.swtaxi = True  # Default ON: Doesn't do anything. See comments of set_taxi function below.
        self.swtaxialt = 1500.0  # Default alt for TAXI OFF
        self.prevconfpairs = set()
        self.confinside_all = 0

        #most important bluesky traffic arrays ()
        with self.settrafarrays():
            self.insdel = np.array([], dtype=bool) # In deletion area or not
            self.insexp = np.array([], dtype=bool) # In experiment area or not
            self.oldalt = np.array([], dtype=float)
            self.distance2D = np.array([], dtype=float)
            self.distance3D = np.array([], dtype=float)
            self.altitude2D = np.array([], dtype=float)
            self.dstart2D = np.array([])
            self.dstart3D = np.array([])
            self.workstart = np.array([])
            self.entrytime = np.array([], dtype=float)
            self.create_time = np.array([], dtype=float)

    def create(self, n=1):
        ''' Create is called when new aircraft are created. '''
        super().create(n)
        self.distance2D[-n:] = 0.0
        self.distance3D[-n:] = 0.0
        self.altitude2D[-n:] = 0.0
        self.dstart2D[-n:] = None
        self.dstart3D[-n:] = None
        self.workstart[-n:] = None
        self.entrytime[-n:] = 0.0
        
        self.oldalt[-n:] = 0.0
        self.insdel[-n:] = False
        self.insexp[-n:] = False
        self.create_time[-n:] = 0.0

    @stack.command()
    def startlog(self):
        ''' Start logger
        '''
        self.flstlog.start()
        self.conflog.start()
        return

    #@timed_function(name='AREA', dt=1.0)
    # can be used to update differently from sim time steps

    def update(self):
        ''' Update flight efficiency metrics
            2D and 3D distance [m], and work done (force*distance) [J] '''
        
        resultantspd = np.sqrt(bs.traf.gs * bs.traf.gs + bs.traf.vs * bs.traf.vs)
        self.distance2D += bs.sim.simdt * bs.traf.gs
        self.distance3D += bs.sim.simdt * resultantspd
        self.altitude2D += bs.sim.simdt * abs(bs.traf.vs)

        # Count new conflicts where at least one of the aircraft is inside
        # the experiment area
        # Store statistics for all new conflict pairs
        # Conflict pairs detected in the current timestep that were not yet
        # present in the previous timestep
        confpairs_new = list(set(bs.traf.cd.confpairs) - self.prevconfpairs)
        if confpairs_new:
            done_pairs = []
            for pair in set(confpairs_new):
                # Check if the aircraft still exist
                if (pair[0] in bs.traf.id) and (pair[1] in bs.traf.id):
                    # Get the two aircraft
                    idx1 = bs.traf.id.index(pair[0])
                    idx2 = bs.traf.id.index(pair[1])
                    done_pairs.append((idx1,idx2))
                    if (idx2,idx1) in done_pairs:
                        continue
                    # extra calculations for conflict parameter

                    self.conflog.log(pair[0], pair[1],
                                    bs.traf.lat[idx1], bs.traf.lon[idx1],bs.traf.alt[idx1],
                                    bs.traf.lat[idx2], bs.traf.lon[idx2],bs.traf.alt[idx2])
            #used to rerun the if statement
            self.prevconfpairs = set(bs.traf.cd.confpairs)

            

            # delete all aicraft in self.delidx
            #if len(delidx) > 0:
             #   bs.traf.delete(delidx)


        # delete if ac is below 300 m / 1000 ft 
        # and distance to destination is < 5NM
        # need to include distance to destination to only delete arrivals
        delete_array = np.where(bs.traf.alt < 300 
                                #and bs.traf.DEST < 2)
        )
        acids_to_delete = np.array(bs.traf.id)[delete_array]
        for acid in acids_to_delete:
            acidx = bs.traf.id2idx(acid)
            self.flst.log(
                acid,
                self.create_time[acidx],
                sim.simt - self.entrytime[acidx],
                self.distance2D[acidx]/nm,
                self.distance3D[acidx]/nm,
                # what is bs.traf.work?!
                bs.traf.work[acidx]*1e-6,
                bs.traf.lat[acidx],
                bs.traf.lon[acidx],
                bs.traf.alt[acidx]/ft,
                bs.traf.tas[acidx]/kts,
                bs.traf.vs[acidx]/fpm,
                bs.traf.hdg[acidx],
                bs.traf.cr.active[acidx],
                bs.traf.aporasas.alt[acidx]/ft,
                bs.traf.aporasas.tas[acidx]/kts,
                bs.traf.aporasas.vs[acidx]/fpm,
                bs.traf.aporasas.hdg[acidx])
            stack.stack(f' DEL {acid}')
        
