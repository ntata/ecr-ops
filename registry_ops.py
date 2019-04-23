import sys
import os
import schedule
import time
from datetime import datetime
import pruneBuilds
import logging
from logstash_formatter import LogstashFormatterV1


def checkenv():
    """
    Method to ensure environment is setup correctly
    """
    if 'AWS_ACCESS_KEY_ID' not in os.environ:
        logger.critical("AWS_ACCESS_KEY_ID is not defined")
        sys.exit(1)

    if 'AWS_SECRET_ACCESS_KEY' not in os.environ:
        logger.critical("AWS_SECRET_ACCESS_KEY is not defined")
        sys.exit(1)

    if 'AWS_DEFAULT_REGION' not in os.environ:
        logger.critical("AWS_DEFAULT_REGION is not defined")
        sys.exit(1)

    if 'REGISTRIES' not in os.environ:
        logger.critical("REGISTRIES is not defined")
        sys.exit(1)

    if 'DELETE_IMAGES' not in os.environ:
        logger.critical("DELETE_IMAGES is not defined")
        sys.exit(1)

    if 'REGISTRY_OPS_ACCESS_TOKEN' not in os.environ:
        logger.critical("REGISTRY_OPS_ACCESS_TOKEN is not defined")
        sys.exit(1)


def main():
    checkenv()

    pb = pruneBuilds.PruneBuilds()
    pb.clean_images()
    schedule.every().day.at('01:00').do(pb.clean_images)
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == '__main__':
    main()
