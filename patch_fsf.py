'''
Tweaks FSForce so that it doesn't try to talk to the sim but instead talks to our dummy window.

Note: depending on where you installed FSForce, you may need to run this from an administrator window
'''

import sys, os, configparser

if __name__ == '__main__':
    args = list(sys.argv[1:])
    if not args:
        print('Usage: python patch_fsf.py <path to your FSForce folder>')
        print('   Ex: python patch_fsf.py "d:\program files (x86)\FSForce 2"')
        sys.exit(1)

    fsfDir = os.path.abspath(args.pop(0))
    if not os.path.isdir(fsfDir):
        print('Error: %s does not exist' % fsfDir)
        sys.exit(1)

    for inFile, outFile in [('FSForce.exe', 'FSForce-89.exe'), ('FSForce_x64.dll', 'FSForce-89_x64.dll')]:
        fullPath = os.path.join(fsfDir, inFile)
        print('Patching', inFile, 'to', outFile)
        with open(fullPath, 'rb') as f:
            data = f.read()
        data = data.replace(b'FS98MAIN', b'FS89MAIN')

        fullPath = os.path.join(fsfDir, outFile)
        with open(fullPath, 'wb') as f:
            f.write(data)

    # Save this dir for later use
    config = configparser.ConfigParser()
    config['FSForce'] = {'Directory':fsfDir}
    with open('config.ini', 'w') as f:
        config.write(f)

