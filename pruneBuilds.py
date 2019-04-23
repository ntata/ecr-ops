import boto3
import sys
import os
import logging
import re
import schedule
import time
import schedule
from datetime import datetime
from logstash_formatter import LogstashFormatterV1
from botocore.exceptions import ClientError
from itertools import groupby
import datetime

from github import Github

# Setup logging for logstash
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logHandler = logging.StreamHandler(sys.stdout)
formatter = LogstashFormatterV1()
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)

access_token = os.environ.get('REGISTRY_OPS_ACCESS_TOKEN', 'na')


class PruneBuilds(object):
    """
    Class that defines methods to clean images
    """

    def __init__(self):
        """
        initialize object with branch name to prune from
        """
        self.client = boto3.client('ecr')
        self.git_obj = Github(access_token)

    def deleteImageByTag(self, repository, tag):
        try:
            response = self.client.batch_delete_image(
                repositoryName=repository, imageIds=[{
                    'imageTag': tag
                }])
            return response
        except ClientError as e:
            if e.response['Error']['Code'] == 'RepositoryNotFoundException':
                print(
                    "Exception Occurred!!! Check REGISTRIES in docker-compose.yml"
                )
            else:
                print(e)

    def deleteImageByDigest(self, repository, digest):
        try:
            self.client.batch_delete_image(
                repositoryName=repository, imageIds=[{
                    'imageDigest': digest
                }])
        except ClientError as e:
            if e.response['Error']['Code'] == 'RepositoryNotFoundException':
                print(
                    "Exception Occurred!!! Check REGISTRIES value in docker-compose.yml"
                )
            else:
                print(e)

    def getAllImages(self, repository):
        """
        using the paginator to return all the images
        """
        try:
            paginator = self.client.get_paginator('list_images')
            page_iterator = paginator.paginate(repositoryName=repository)
            images = []
            for page in page_iterator:
                for image in page['imageIds']:
                    images.append(image)
            return images
        except ClientError as e:
            if e.response['Error']['Code'] == 'RepositoryNotFoundException':
                print(
                    "Exception Occurred!!! Check REGISTRIES in docker-compose.yml"
                )
            else:
                print(e)

    def filterNoTags(self, imageList):
        has_tags = []
        for i in imageList:
            for k in i.keys():
                if k == 'imageTag':
                    has_tags.append(i)
        return has_tags

    def splitBranchBuild(self, tag):
        """
        take an image tag in the format branch-buildNo, and split them out with a regexp
        """
        splitImages = {}

        #regex for identifying images that are not *-rc-* or versions (12.4.9)
        nonVersionRegexp = re.compile(
            r'(c-)?(?P<branch>(?!.*rc).*)-(?P<buildNo>[0-9]+$)')

        # regex to identify versions only (12.4.9)
        versionRegexp = re.compile(
            r'(c-)?(?P<major>([0-9]*))\.(?P<minor>([0-9]*))\.(?P<patch>([0-9]*)+$)')

        # regex to identify *-rc-* only
        rcRegexp = re.compile(
            r'(c-)?(?P<major>([0-9]*))\.(?P<minor>([0-9]*))\.(?P<patch>([0-9]*))-rc-(?P<buildNo>([0-9]*)+$)'
        )

        nonVersion_match = nonVersionRegexp.match(tag)
        version_match = versionRegexp.match(tag)
        rc_match = rcRegexp.match(tag)


        if nonVersion_match:
            return {
                "tag": tag,
                "branch": nonVersion_match.group('branch'),
                "buildNo": int(nonVersion_match.group('buildNo'))
            }
        elif version_match:
            return {
                "tag": tag,
                "major": int(version_match.group('major')),
                "minor": int(version_match.group('minor')),
                "patch": int(version_match.group('patch'))
            }
        elif rc_match:
            return {
                "tag": tag,
                "major": int(rc_match.group('major')),
                "minor": int(rc_match.group('minor')),
                "patch": int(rc_match.group('patch')),
                "buildNo": int(rc_match.group('buildNo'))
            }
        else:
            return None

    def deleteOldBuilds(self, imageList):
        """
        Given a list of images, keep images based on the following criteria:
        - last 10 images for 'develop' branch
        - last 10 images for 'master' branch
        - last 2 images for 'feature' branch e.g. pid-543
        - last 3 verions builds for both 'rc' and 'versions' i.e. if current release is 12.7.6, 
          we keep 12.7.\*, 12.6.\* and 12.5.\* and discard the rest.
        """
        onlyTagged = self.filterNoTags(imageList)
        # we're only concerned with the tags, drop the digests
        onlyTagged = [i['imageTag'] for i in onlyTagged]
        splitImages = [
            self.splitBranchBuild(i) for i in onlyTagged
            if self.splitBranchBuild(i) is not None
        ]

        splitImages_develop = []
        splitImages_master = []
        splitImages_feature = []
        splitImages_version = []
        splitImages_rc = []

        for i in splitImages:
            try:
                if 'branch' in i:
                    if i['branch'] == 'develop':
                        splitImages_develop.append(i)
                    elif i['branch'] == 'master':
                        splitImages_master.append(i)
                    else:
                        splitImages_feature.append(i)
                else:
                    if 'buildNo' in i:
                        splitImages_rc.append(i)
                    else:
                        splitImages_version.append(i)
            except Exception as e:
                print(e)

        toDeleteOutput_develop = []
        toDeleteOutput_master = []
        toDeleteOutput_feature = []
        toDeleteOutput_version = []
        toDeleteOutput_rc = []

        #list to maintain individual feature branch's builds count
        splitImages_feature_branches = []

        if len(splitImages_develop) <= 10:
            # If there are 10 or less we don't need to do anything
            toDeleteOutput_develop = []
        if len(splitImages_develop) > 10:
            # otherwise order them by latest, send back a list of tags to delete
            splitImages_develop.sort(key=lambda x: x['buildNo'], reverse=True)
            toDelete = splitImages_develop[10:]
            toDeleteOutput_develop = toDeleteOutput_develop + [
                i['tag'] for i in toDelete
            ]

        if len(splitImages_master) <= 10:
            # If there are 10 or less we don't need to do anything
            toDeleteOutput_master = []
        if len(splitImages_master) > 10:
            # otherwise order them by latest, send back a list of tags to delete
            splitImages_master.sort(key=lambda x: x['buildNo'], reverse=True)
            toDelete = splitImages_master[10:]
            toDeleteOutput_master = [i['tag'] for i in toDelete]

        if len(splitImages_feature) <= 1:
            # If there is 1 image or less we don't need to do anything
            toDeleteOutput_feature = []
        if len(splitImages_feature) > 1:
            # otherwise order them by latest, send back a list of tags to delete
            for key, group in groupby(splitImages_feature,
                                      lambda item: item['branch']):
                splitImages_feature_branches.append(key)
            splitImages_feature.sort(key=lambda x: x['buildNo'], reverse=True)
            for i in splitImages_feature_branches:
                featureBranch = [
                    k['branch'] for k in splitImages_feature
                    if k['branch'] == i
                ]
                if len(featureBranch) <= 1:
                    pass
                else:
                    toDelete_feature = [
                        item for item in splitImages_feature
                        if item['branch'] == i
                    ]
                    toDelete = toDelete_feature[1:]
                    temp = [item['tag'] for item in toDelete]
                    toDeleteOutput_feature = toDeleteOutput_feature + temp

        # handle version (12.6.2) and RC (12.8.0-rc-2) builds
        if len(splitImages_version) > 1 and len(splitImages_rc) > 1:
            splitImages_version.sort(
                key=lambda x: (x['major'], x['minor'], x['patch']),
                reverse=True)
            # new logic to handle new versioning to follow <year>-<month>-<build_number> and
            # <year>-<month>-<build_number>-rc-<build>
            todays_date = datetime.datetime.today().strftime('%y-%m-%d')
            latest_major_ver = int(todays_date.split('-')[0])
            latest_minor_ver = int(todays_date.split('-')[1])
            for i in splitImages_version:
                if latest_minor_ver >= 3:
                    if i['major'] < latest_major_ver or i['minor'] < (
                            latest_minor_ver - 2):
                        toDeleteOutput_version.append(i['tag'])
                elif latest_minor_ver == 2:
                    if i['major'] < latest_major_ver and i['minor'] < 12:
                        toDeleteOutput_version.append(i['tag'])
                else: #latest_minor_ver == 1
                    if i['major'] < latest_major_ver and i['minor'] < 11:
                        toDeleteOutput_version.append(i['tag'])

            # handle release candidate **-rc-** builds
            # new logic to handle new versioning to follow <year>-<month>-<build_number> and
            # <year>-<month>-<build_number>-rc-<build>
            splitImages_rc.sort(
                key=lambda x: (x['major'], x['minor'], x['patch']),
                reverse=True)
            for i in splitImages_rc:
                if latest_minor_ver >= 3:
                    if i['major'] < latest_major_ver or i['minor'] < (
                            latest_minor_ver - 2):
                        toDeleteOutput_version.append(i['tag'])
                elif latest_minor_ver == 2:
                    if i['major'] < latest_major_ver and i['minor'] < 12:
                        toDeleteOutput_version.append(i['tag'])
                else: #latest_minor_ver == 1
                    if i['major'] < latest_major_ver and i['minor'] < 11:
                        toDeleteOutput_version.append(i['tag'])

        toDeleteOutput = toDeleteOutput_develop + toDeleteOutput_master + toDeleteOutput_feature + toDeleteOutput_version + toDeleteOutput_rc
        return {"Reason": "Old-builds", "ImageTags": toDeleteOutput}

    def getGitRepoBranches(self, REPOSITORY):
        try:
            git_repo_obj = self.git_obj.get_repo(REPOSITORY.strip('\''))
            git_repo_branches_obj = git_repo_obj.get_branches()
            git_branches = []
            for branch in git_repo_branches_obj:
                git_branches.append(branch.name.lower())
            return git_branches
        except Error as e:
            print(e)

    def deleteClosedGitBranches(self, REPOSITORY, imageList, gitBranches):
        """
        method to identify closed github branches in a  repository
        """
        #regex for dropping *-rc* and version branches
        branchRegexp = re.compile(
            r'(?P<branch>((?!.*rc)[-_A-Za-z0-9]*))-(?P<buildNo>[0-9]+$)')
        onlyTagged = self.filterNoTags(imageList)
        imageTags = [i['imageTag'] for i in onlyTagged]
        #create a list to consider feature branch tags that are not version numbers or *-rc*
        featureBranchTags = []
        for tag in imageTags:
            if branchRegexp.match(tag):
                featureBranchTags.append(tag)
        #ecr_image_set contains unique set of image tags without the build number *-[0-9]$
        ecr_images_set = []
        for image in featureBranchTags:
            if image.startswith('c-'):
                ecr_images_set.append(image.rsplit('-', 1)[1])
            else:
                ecr_images_set.append(image.rsplit('-', 1)[0])
        ecr_images_set = set(ecr_images_set)
        unmatched = list(set(ecr_images_set).difference(set(gitBranches)))
        git_closed_branch_tags = []
        for branch in unmatched:
            for tag in onlyTagged:
                if tag['imageTag'].rsplit('-', 1)[0] == branch or tag['imageTag'].rsplit('-', 1)[1] == branch:
                    git_closed_branch_tags.append(tag['imageTag'])
        return {
            "Reason": "ClosedGitBranches",
            "ImageTags": git_closed_branch_tags
        }

    def getOrphans(self, imageList):
        """
        Given a list of images, identify the ones without Tags (orphans)
        """
        images_to_delete = []
        if len(imageList) == 0:
            return {"Reason": "ImageNoTag", "Images": []}
        else:
            for image in imageList:
                try:
                    tag = image['imageTag']
                except:
                    images_to_delete.append(image['imageDigest'])
            return {"Reason": "ImageNoTag", "ImageDigests": images_to_delete}

    def clean_images(self):
        try:
            DELETE = int(os.environ.get("DELETE_IMAGES"))
        except:
            logger.critical("Invalid value for DELETE_IMAGES")
            sys.exit(1)

        toScan = os.environ.get("REGISTRIES").split(',')

        if len(toScan) < 1:
            logger.critical("Invalid registries")
            sys.exit(1)

        for REPOSITORY in toScan:
            toDeleteTags = []
            images = self.getAllImages(REPOSITORY)
            logger.info(
                "There are {0} images in {1}".format(len(images), REPOSITORY))

            #deleteClosedGitBranches
            logger.info(
                "Now looking at closed github branches detected by deleteClosedGitBranches"
            )
            gitBranches = self.getGitRepoBranches(REPOSITORY)
            gitBranchResult = self.deleteClosedGitBranches(
                REPOSITORY, images, gitBranches)
            toDeleteTags = toDeleteTags + [
                i for i in gitBranchResult['ImageTags']
            ]
            logger.info(gitBranchResult)
            if int(DELETE) == 0:
                for tag in toDeleteTags:
                    logger.info(
                        "Would have deleted {0}/{1} identified by deleteClosedGitBranches".
                        format(REPOSITORY, tag))

            #deleteOldBuilds
            logger.info("Now looking at images identified by deleteOldBuilds")
            imagesResult = self.deleteOldBuilds(images)
            toDeleteTags = toDeleteTags + [
                i for i in imagesResult['ImageTags']
            ]
            toDeleteTags = list(set(toDeleteTags))
            logger.info(imagesResult)

            if (DELETE) == 0:
                for tag in imagesResult['ImageTags']:
                    logger.info(
                        "Would have deleted {0}/{1} identified by deleteOldBuilds".
                        format(REPOSITORY, tag))

            #Now proceeding to delete images if DELETE flag is set
            if (DELETE) == 1:
                logger.info(
                    "Now deleting images identified by deleteOldBuilds & deleteClosedGitBranches"
                )
                for tag in toDeleteTags:
                    logger.info(
                        "Deleting {0}/{1} identifiled by deleteOldBuilds or deleteClosedGitBranches".
                        format(REPOSITORY, tag))
                    result = self.deleteImageByTag(REPOSITORY, tag)

            #Orphan Digests
            logger.info("Now looking at images identified by getOrphans")
            orphanResult = self.getOrphans(images)
            logger.info(orphanResult['ImageDigests'])
            for digest in orphanResult['ImageDigests']:
                if int(DELETE) == 1:
                    logger.info("Deleting {0}/{1} identified by getOrphans".
                                format(REPOSITORY, digest))
                    result = self.deleteImageByDigest(REPOSITORY, digest)
                else:
                    logger.info(
                        "Would have deleted {0}/{1} identified by getOrphans".
                        format(REPOSITORY, digest))
