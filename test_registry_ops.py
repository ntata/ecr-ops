import boto3
import random
import string
from moto import mock_ecr
import pytest
import unittest
from pruneBuilds import PruneBuilds
from unittest.mock import patch


class registryOpsTestCase(unittest.TestCase):
    """
    Class with test cases to test registry_ops
    """

    #TODO:
    # 1. port unittest style of testcases to pytest with fixtures
    # 2. add exception handling to boto3 api calls?

    #initialize pruneBuilds class
    test_pb = PruneBuilds()

    @mock_ecr
    def setUp(self):
        """
        TODO: move self.client creation and test repository creation here.
        """
        self.client = boto3.client('ecr', region_name='us-west-2')

    @mock_ecr
    def tear_down():
        """
        delete all the test repositories created
        """
        self.client.delete_repository(
            repositoryName='TestRepositoryOrphans', force=True)
        self.client.delete_repository(
            repositoryName='TestRepositoryOldDevelop50', force=True)
        self.client.delete_repository(
            repositoryName='TestRepositoryOldMaster50', force=True)
        self.client.delete_repository(
            repositoryName='TestRepositoryOldDevelop10', force=True)
        self.client.delete_repository(
            repositoryName='TestRepositoryOldMaster10', force=True)
        self.client.delete_repository(
            repositoryName='TestRepository5', force=True)

    def generateFakeDigest(self):
        return 'sha256:' + ''.join(random.choices('0123456789abcdef', k=64))

    def test_splitBranchBuild(self):
        """
        given a branch-buildNo, test splitting them into tag, branch, buildNo,
        major, minor and patch
        """
        dev_match = "c-develop-27"
        master_match = "master-25"
        feature_match = "c-cw-822-3"
        rc_match = "12.9.8-rc-4"
        version_match = "c-12.22.2"

        dev_match_result = self.test_pb.splitBranchBuild(dev_match)
        assert dev_match_result is not None
        assert dev_match_result['branch'] == 'develop'
        assert dev_match_result['buildNo'] == 27
        master_match_result = self.test_pb.splitBranchBuild(master_match)
        assert master_match_result is not None
        assert master_match_result['branch'] == 'master'
        assert master_match_result['buildNo'] == 25
        feature_match_result = self.test_pb.splitBranchBuild(feature_match)
        assert feature_match_result is not None
        assert feature_match_result['branch'] == 'cw-822'
        assert feature_match_result['buildNo'] == 3

        rc_match_result = self.test_pb.splitBranchBuild(rc_match)
        assert rc_match_result is not None
        assert rc_match_result['major'] == 12
        assert rc_match_result['minor'] == 9
        assert rc_match_result['patch'] == 8
        assert rc_match_result['buildNo'] == 4
        version_match_result = self.test_pb.splitBranchBuild(version_match)
        assert version_match_result is not None
        assert version_match_result['major'] == 12
        assert version_match_result['minor'] == 22
        assert version_match_result['patch'] == 2

    def test_FilterNoTags(self):
        """
        given a list of objects some with tags, filter out the ones that don't have tags
        """
        hasTags = [{
            "imageTag": "v1.0",
            "imageDigest": "abc123"
        }, {
            "imageDigest": "def456"
        }]
        filterResults = self.test_pb.filterNoTags(hasTags)
        assert len(filterResults) == 1
        assert filterResults[0]['imageDigest'] == 'abc123'

    def test_FilterNoTagsEmpty(self):
        """
        given a list of objects none with tags, filter out the ones that don't have tags
        """
        noTags = [{"imageDigest": "abc123"}, {"imageDigest": "def456"}]
        filterResults = self.test_pb.filterNoTags(noTags)

    @mock_ecr
    def test_getAllImages(self):
        """
        test with 5 images (result should not require pagination )
        """
        self.client.create_repository(repositoryName='TestRepository5')
        for i in range(0, 5):
            self.client.put_image(
                repositoryName='TestRepository5',
                imageManifest=self.generateFakeDigest(),
                imageTag="c-myTag-{0}".format(i))

        # Get the images
        images = self.test_pb.getAllImages('TestRepository5')
        assert len(images) == 5

    @mock_ecr
    def test_deleteImagesLessThanRequired(self):
        """
        create 10 images for the develop branch,
        10 images for master branch, 1 image for feature, 2 images
        for versions and 2 images for rc
        and when these set of images are passed to deleteOldBuilds,
        should return an empty list to delete
        """
        self.client.create_repository(repositoryName='TestRepository21')
        for i in range(0, 24):
            if i < 10:
                self.client.put_image(
                    repositoryName='TestRepository21',
                    imageManifest=''.join(
                        random.choices(string.ascii_lowercase, k=200)),
                    imageTag="c-develop-{0}".format(i))
            if (i > 9 and i < 20):
                self.client.put_image(
                    repositoryName='TestRepository21',
                    imageManifest=''.join(
                        random.choices(string.ascii_lowercase, k=200)),
                    imageTag="c-master-{0}".format(i))
            if (i > 19 and i < 21):
                self.client.put_image(
                    repositoryName='TestRepository21',
                    imageManifest=''.join(
                        random.choices(string.ascii_lowercase, k=200)),
                    imageTag="c-feature-{0}".format(i))
            if (i > 20 and i < 24):
                self.client.put_image(
                    repositoryName='TestRepository21',
                    imageManifest=''.join(
                        random.choices(string.ascii_lowercase, k=200)),
                    imageTag="c-19.{0}.6".format(i))
                self.client.put_image(
                    repositoryName='TestRepository21',
                    imageManifest=''.join(
                        random.choices(string.ascii_lowercase, k=200)),
                    imageTag="c-19.{0}.6-rc-{0}".format(i))
        imageList = self.test_pb.getAllImages('TestRepository21')
        deleteResults = self.test_pb.deleteOldBuilds(imageList)
        assert deleteResults['Reason'] == 'Old-builds'
        assert deleteResults['ImageTags'] == []

    @mock_ecr
    def test_deleteOldBuildsGreaterThanRequired(self):
        """
        create 12 images for develop, 12 images for master, 3 images for feature branches,
        4 images for versions, 4 images with rcs and pass them all to deleteOldBuilds. 
        Results should include only the old 2 builds of develop, old 2 builds for master,
        oldest build for feature branch, oldest version build and oldest rc build
        """
        self.client.create_repository(repositoryName='TestRepository31')

        # these are images that definitely need to marked for deletion based on the
        # logic for keeping only last 3 builds of versions and rc's
        definite_deletes = ['18.10.0', '18.2.5', '17.3.3-rc-2', '12.4.5-rc-2']

        for i in definite_deletes:
            self.client.put_image(
                repositoryName='TestRepository31',
                imageManifest=''.join(
                    random.choices(string.ascii_lowercase, k=200)),
                imageTag=i)
        for i in range(1, 32):
            if i < 13:
                self.client.put_image(
                    repositoryName='TestRepository31',
                    imageManifest=''.join(
                        random.choices(string.ascii_lowercase, k=200)),
                    imageTag="develop-{0}".format(i))
            if (i > 12 and i < 25):
                self.client.put_image(
                    repositoryName='TestRepository31',
                    imageManifest=''.join(
                        random.choices(string.ascii_lowercase, k=200)),
                    imageTag="master-{0}".format(i))
            if (i > 24 and i < 28):
                self.client.put_image(
                    repositoryName='TestRepository31',
                    imageManifest=''.join(
                        random.choices(string.ascii_lowercase, k=200)),
                    imageTag="feature-{0}".format(i))
            if (i > 27 and i < 32):
                self.client.put_image(
                    repositoryName='TestRepository31',
                    imageManifest=''.join(
                        random.choices(string.ascii_lowercase, k=200)),
                    imageTag="19.1.{0}".format(i))
                self.client.put_image(
                    repositoryName='TestRepository31',
                    imageManifest=''.join(
                        random.choices(string.ascii_lowercase, k=200)),
                    imageTag="19.2.{0}-rc-{0}".format(i))
        # added circleci build imagetags
        self.client.put_image(
            repositoryName='TestRepository31',
            imageManifest=''.join(
                random.choices(string.ascii_lowercase, k=200)),
            imageTag="19.1.6-rc-12")
        self.client.put_image(
            repositoryName='TestRepository31',
            imageManifest=''.join(
                random.choices(string.ascii_lowercase, k=200)),
            imageTag="c-19.2.6-rc-12")

        imageList = self.test_pb.getAllImages('TestRepository31')
        deleteResults = self.test_pb.deleteOldBuilds(imageList)
        assert deleteResults['Reason'] == 'Old-builds'
        assert len(deleteResults['ImageTags']) == 10
        assert 'develop-11' not in deleteResults['ImageTags']
        assert 'master-21' not in deleteResults['ImageTags']
        assert 'feature-27' not in deleteResults['ImageTags']
        assert 'develop-1' in deleteResults['ImageTags']
        assert 'master-13' in deleteResults['ImageTags']
        assert 'feature-25' in deleteResults['ImageTags']
        for i in definite_deletes:
            assert i in deleteResults['ImageTags']

    @mock_ecr
    def test_getOrphans(self):
        """
        create an image with a digest and one without. we should delete the 
        one without and leave the one with
        """
        self.client.create_repository(repositoryName='TestRepositoryOrphans')
        self.client.put_image(
            repositoryName='TestRepositoryOrphans', imageManifest='Orphan')
        self.client.put_image(
            repositoryName='TestRepositoryOrphans',
            imageTag='NotOrphan',
            imageManifest='NotOrphanDigest')

        imageList = self.test_pb.getAllImages('TestRepositoryOrphans')
        deleteOrphanResults = self.test_pb.getOrphans(imageList)
        assert deleteOrphanResults['Reason'] == 'ImageNoTag'
        assert len(deleteOrphanResults['ImageDigests']) == 1
        # Sanity test, the list should have had two images on it
        assert len(imageList) == 2

    @mock_ecr
    @patch(
        'pruneBuilds.PruneBuilds.getGitRepoBranches',
        return_value=[
            'pw-123', 'cw-123', 'develop', 'master', 'bw-123', '12.1.0',
            '12.1.0-rc', 'mytag-1', 'c-pid'
        ])
    def test_deleteClosedGitBranches(self, getGitRepoBranchesMock):
        """
        create an ECR repository with image-tags of all kinds, and also create a
        mocked list of github branches for the same repository to test if closed github
        branches are being identified to delete
        """
        self.client.create_repository(repositoryName='TestRepositoryWithGit')
        for i in range(0, 39):
            if (i < 5):
                self.client.put_image(
                    repositoryName='TestRepositoryWithGit',
                    imageManifest=self.generateFakeDigest(),
                    imageTag="pw-6532-{0}".format(i))
            if (5 < i < 19):
                self.client.put_image(
                    repositoryName='TestRepositoryWithGit',
                    imageManifest=self.generateFakeDigest(),
                    imageTag="develop-{0}".format(i))
            if (19 < i < 33):
                self.client.put_image(
                    repositoryName='TestRepositoryWithGit',
                    imageManifest=self.generateFakeDigest(),
                    imageTag="master-{0}".format(i))
            if (33 < i < 36):
                self.client.put_image(
                    repositoryName='TestRepositoryWithGit',
                    imageManifest=self.generateFakeDigest(),
                    imageTag="myTag-rc-{0}".format(i))
            if (36 < i < 39):
                self.client.put_image(
                    repositoryName='TestRepositoryWithGit',
                    imageManifest=self.generateFakeDigest(),
                    imageTag="12.1.0-{0}".format(i))
        self.client.put_image(
            repositoryName='TestRepositoryWithGit',
            imageManifest=self.generateFakeDigest(),
            imageTag="c-cr-2")

        git_branches = [
            'pw-123', 'cw-123', 'develop', 'master', 'bw-123', '12.1.0',
            '12.1.0-rc', 'mytag-1', 'c-pid'
        ]
        self.assertEqual(
            getGitRepoBranchesMock('TestRepositoryWithGit'), git_branches)

        # asserting if calling mocked methods is indeed replacing call
        # for the original method
        assert getGitRepoBranchesMock is self.test_pb.getGitRepoBranches
        self.test_pb.getGitRepoBranches.assert_called_with(
            'TestRepositoryWithGit')
        imageList = self.test_pb.getAllImages('TestRepositoryWithGit')
        gitClosedBranchTags = self.test_pb.deleteClosedGitBranches(
            'TestRepositoryWithGit', imageList, git_branches)
        # 5 tags with name pw-6532-{} will have to be outputed
        gitClosedBranchTagsList = [i for i in gitClosedBranchTags['ImageTags']]
        assert len(gitClosedBranchTagsList) == 7
        assert 'pw-6532-1' in gitClosedBranchTagsList
        assert 'develop-18' not in gitClosedBranchTagsList
        assert 'develop-6' not in gitClosedBranchTagsList
        assert '12.1.0-rc' not in gitClosedBranchTagsList
        assert 'c-cr-2' in gitClosedBranchTagsList


if __name__ == "__main__":
    unittest.main()
