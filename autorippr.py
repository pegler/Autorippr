"""
Autorippr

Ripping
    Uses MakeMKV to watch for movies inserted into DVD/BD Drives

    Automaticly checks for existing directory/movie and will NOT overwrite existing
    files or folders

    Checks minimum length of video to ensure movie is ripped not previews or other
    junk that happens to be on the DVD

    DVD goes in > MakeMKV gets a proper DVD name > MakeMKV Rips

Compressing
    An optional additional used to rename and compress movies to an acceptable standard
    which still delivers quality audio and video but reduces the file size
    dramatically.

    Using a nice value of 15 by default, it runs HandBrake (or FFmpeg) as a background task
    that allows other critical tasks to complete first.

Extras


Released under the MIT license
Copyright (c) 2014, Jason Millward

@category   misc
@version    $Id: 1.6.3, 2015-03-09 19:16:11 ACDT $;
@author     Jason Millward <jason@jcode.me>
@license    http://opensource.org/licenses/MIT

Usage:
    autorippr.py   ( --rip | --compress | --extra )  [options]
    autorippr.py   ( --rip [ --compress ] )          [options]
    autorippr.py   --all                             [options]
    autorippr.py   --test

Options:
    -h --help       Show this screen.
    --version       Show version.
    --debug         Output debug.
    --rip           Rip disc using makeMKV.
    --compress      Compress using HandBrake or FFmpeg.
    --extra         Lookup, rename and/or download extras.
    --all           Do everything
    --test          Tests config and requirements
    --silent        Silent mode

"""

import os
import sys
import yaml
import subprocess
import tempfile
from classes import *
from lockfile import LockFile, LockError

__version__ = "1.6.3"

DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_FILE = "%s/settings.cfg" % DIR

RIP_LOCK = LockFile(os.path.normpath(tempfile.gettempdir() + '/autorippr_rip.lock'), timeout=1)
COMPRESS_LOCK = LockFile(os.path.normpath(tempfile.gettempdir() + '/autorippr_compress.lock'), timeout=1)
EXTRA_LOCK = LockFile(os.path.normpath(tempfile.gettempdir() + '/autorippr_extra.lock'), timeout=1)


def eject(config, drive):
    """
        Ejects the DVD drive
        Not really worth its own class
    """
    log = logger.Logger("Eject", config['debug'], config['silent'])

    log.debug("Ejecting drive: " + drive)
    log.debug("Attempting OS detection")

    try:
        if sys.platform == 'win32':
            log.debug("OS detected as Windows")
            import ctypes
            ctypes.windll.winmm.mciSendStringW(
                "set cdaudio door open", None, drive, None)

        elif sys.platform == 'darwin':
            log.debug("OS detected as OSX")
            p = os.popen("drutil eject " + drive)

            while 1:
                line = p.readline()
                if not line:
                    break
                log.debug(line.strip())

        else:
            log.debug("OS detected as Unix")
            p = os.popen("eject -vm " + drive)

            while 1:
                line = p.readline()
                if not line:
                    break
                log.debug(line.strip())

    except Exception as ex:
        log.error("Could not detect OS or eject CD tray")
        log.ex("An exception of type %s occured." % type(ex).__name__)
        log.ex("Args: \r\n %s" % ex.args)

    finally:
        del log


def rip(config):
    """
        Main function for ripping
        Does everything
        Returns nothing
    """
    log = logger.Logger("Rip", config['debug'], config['silent'])

    mkv_save_path = config['makemkv']['savePath']

    log.debug("Ripping initialised")
    mkv_api = makemkv.MakeMKV(config)

    log.debug("Checking for DVDs")
    dvds = mkv_api.find_disc()

    log.debug("%d DVDs found" % len(dvds))

    if len(dvds) > 0:
        # Best naming convention ever
        for dvd in dvds:
            mkv_api.set_title(dvd["discTitle"])
            mkv_api.set_index(dvd["discIndex"])

            movie_title = mkv_api.get_title()

            movie_path = '%s/%s' % (mkv_save_path, movie_title)
            if not os.path.exists(movie_path):
                os.makedirs(movie_path)

                dbmovie = database.insert_movie(
                    movie_title,
                    movie_path,
                    config['filebot']['enable']
                )

                database.insert_history(
                    dbmovie,
                    "Movie added to database"
                )

                mkv_api.get_disc_info()

                if len( mkv_api.get_savefile() ) != 0:
                    database.update_movie(dbmovie, 3, mkv_api.get_savefile())

                    with stopwatch.StopWatch() as t:
                        database.insert_history(
                            dbmovie,
                            "Movie submitted to MakeMKV"
                        )
                        status = mkv_api.rip_disc(mkv_save_path)

                    if status:
                        log.info("It took %s minute(s) to complete the ripping of %s" %
                                (t.minutes, movie_title)
                                )

                        database.update_movie(dbmovie, 4)

                    else:
                        log.info("MakeMKV did not did not complete successfully")
                        log.info("See log for more details")
                        log.debug("Movie title: %s" % movie_title)

                        database.insert_history(
                            dbmovie,
                            "MakeMKV failed to rip movie"
                        )

                        database.update_movie(dbmovie, 2)
                else:
                 log.info("No movie titles found")
                 log.info("Try decreasing 'minLength' in the config and try again")

            else:
                log.info("Movie folder %s already exists" % movie_title)

            if config['makemkv']['eject']:
                eject(config, dvd['location'])

    else:
        log.info("Could not find any DVDs in drive list")


def compress(config):
    """
        Main function for compressing
        Does everything
        Returns nothing
    """
    log = logger.Logger("Compress", config['debug'], config['silent'])

    comp = compression.Compression(config)

    log.debug("Compressing initialised")
    log.debug("Looking for movies to compress")

    dbmovie = database.next_movie_to_compress()

    if dbmovie is not None:
        if comp.check_exists(dbmovie) is not False:

            database.update_movie(dbmovie, 5)

            log.info("Compressing %s" % dbmovie.moviename)

            with stopwatch.StopWatch() as t:
                status = comp.compress(
                    args=config['compress']['com'],
                    nice=int(config['compress']['nice']),
                    dbmovie=dbmovie
                )

            if status:
                log.info("Movie was compressed and encoded successfully")

                log.info(("It took %s minutes to compress %s" %
                          (t.minutes, dbmovie.moviename))
                         )

                database.insert_history(
                    dbmovie,
                    "Compression Completed successfully"
                )

                database.update_movie(
                    dbmovie, 6, filename="%s.mkv" % dbmovie.moviename)

                comp.cleanup()

            else:
                database.update_movie(dbmovie, 5)

                database.insert_history(dbmovie, "Compression failed", 4)

                log.info("Compression did not complete successfully")
        else:
            database.update_movie(dbmovie, 2)

            database.insert_history(
                dbmovie, "Input file no longer exists", 4
            )

    else:
        log.info("Queue does not exist or is empty")


def extras(config):
    """
        Main function for filebotting
        Does everything
        Returns nothing
    """
    log = logger.Logger("Extras", config['debug'], config['silent'])

    fb = filebot.FileBot(config['debug'], config['silent'])

    dbmovie = database.next_movie_to_filebot()

    if dbmovie is not None:
        log.info("Attempting movie rename")

        database.update_movie(dbmovie, 7)

        status = fb.rename(dbmovie)

        if status[0]:
            log.info("Rename success")
            database.update_movie(dbmovie, 6, filename=status[1])

            if config['filebot']['subtitles']:
                log.info("Grabbing subtitles")

                status = fb.get_subtitles(
                    dbmovie, config['filebot']['language'])

                if status:
                    log.info("Subtitles downloaded")
                    database.update_movie(dbmovie, 8)

                else:
                    log.info("Subtitles not downloaded, no match")
                    database.update_movie(dbmovie, 8)

                log.info("Completed work on %s" % dbmovie.moviename)

                if config['commands'] is not None and len(config['commands']) > 0:
                    for com in config['commands']:
                        subprocess.Popen(
                            [com],
                            stderr=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            shell=True
                        )

            else:
                log.info("Not grabbing subtitles")
                database.update_movie(dbmovie, 8)

        else:
            log.info("Rename failed")

    else:
        log.info("No movies ready for filebot")


if __name__ == '__main__':
    arguments = docopt.docopt(__doc__, version=__version__)
    config = yaml.safe_load(open(CONFIG_FILE))

    config['debug'] = arguments['--debug']

    config['silent'] = arguments['--silent']

    if bool(config['analytics']['enable']):
        analytics.ping(__version__)

    if arguments['--test']:
        testing.perform_testing(config)

    if arguments['--rip'] or arguments['--all']:
        try:
            with RIP_LOCK:
                rip(config)
        except LockError:
            pass

    if arguments['--compress'] or arguments['--all']:
        try:
            with COMPRESS_LOCK:
                compress(config)
        except LockError:
            pass

    if arguments['--extra'] or arguments['--all']:
        try:
            with EXTRA_LOCK:
                extras(config)
        except LockError:
            pass
