# SimConMan
Experiments with getting SimConnect-based plugins to work with newer flight sims

## Overview
The core idea is based on the following:
- I have a force-feedback enabled flight yoke.
- I was using Prepar3D as my flight simulator.
- I was using the [FSForce plugin](http://www.fs-force.com/).
- I switched to the [FlyInside Flight Simulator](https://flyinside-fsx.com/Home/Sim) but it doesn't (yet) support FF yokes.
- FSForce doesn't yet work with FlyInside.

The solution I chose was to write a "shim" layer that translates between the plugin and the flight sim: 
- create a standalone server acts as the bridge between the sim and the legacy plugin
- use the FlyInside SDK to create a new plugin that hooks into the sim and talks to the bridge
- in the bridge, implement a subset of the [SimConnect API](https://docs.microsoft.com/en-us/previous-versions/microsoft-esp/cc526983)
- configure the legacy plugin to talk to the bridge

Although the main goal is to bridge the specific force feedback plugin with the FlyInside simulator, the SimConnect code in particular may be useful in other projects, and the overall approach could (in theory) be used for other legacy plugins.
