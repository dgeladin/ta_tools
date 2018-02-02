##!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=too-many-instance-attributes
r"""
For the purposes of this file, we assume that a student is either a student
or a team to make parsing easier, since most of the logic is identical.

See download_submission.process_assignment to see how to utilize this class
correctly.

TODO:
  * Many of the methods of process_repos should be combined?
"""


__all__ = ["Submissions", ] # Controls what can be imported
__author__ = "David Tran, Travis Janssen"
__credits__ = ["David Tran", "Travis Janssen"]
__status__ = "Production"
__version__ = "1.0.0"


from datetime import datetime, timedelta
import inspect
import json
import itertools
import os
import platform
import re
import subprocess

import logging
logger = logging.getLogger(__name__)

class Submissions(object):
    r"""
    The purpose of this class is to download and process students' submissions.

    This will not grade the submission, rather we automate the process of
    acquiring the student's repos.

    """


    def __init__(self, is_team, should_pull_repo_flag):
        r"""
        Defines the variables for the current class.

        We could define static variables but they are not private and
        are publicly accessible in Python.

        Arguments:
          self.is_team:   (boolean) Sets if this submission is a team project
            or not.

          should_pull_repo_flag:   (boolean) Sets if we should git pull,
            if needed.

        """


        # Pattern Matching
        self.DATETIME_PATTERN = '%Y-%m-%dT%H:%M:%S'
        self.REGEX_PATTERN = '^[0-9]{4}(-[0-9]{2}){2}T[0-9]{2}(:[0-9]{2}){2}$'
        self.T_SQUARE_DATETIME_PATTERN = '%Y%m%d%H%M%S'

        # Constants for the class
        self.FOLDER_PREFIX = '6300Spring18'
        self.GIT_CONTEXT = 'gt-omscs-se-2018spring'

        self.STUDENT_RECORDS_FILENAME = 'student_records.json'
        self.STUDENT_ALIAS_FILENAME = 'student_aliases.json'
        self.TEAM_RECORDS_FILENAME = 'student_records_teams.json'
        self.TEAM_MEMBERS_FILENAME = 'student_records_team_members.json'
        self.TIMESTAMP_FILENAME = 'timestamp.txt'

        self.MAIN_REPO_DIR = 'student_repo'
        self.PLATFORM = "CANVAS"
        self.PLATFORMS_VALID = ["CANVAS", "TSQUARE"]
        self.ENCODING = "utf-8"

        # Stored to be used in later logic, so typos between copies don't exist
        self.STR_INVALID = "Invalid"
        self.STR_LATE = "Late"
        self.STR_MISSING = "Missing"
        self.STR_NA = "N/A"
        self.STR_OK = "Ok"
        self.BAD_STR_LIST = [self.STR_INVALID, self.STR_MISSING]

        # Actual non-constant attributes

        # Cache results
        self.cached_file_dicts = {}  # Cache dictionary pulls
        self.cached_teams_pulled = set() # Cache pulled teams

        self.OS_TYPE = platform.system()

        self.is_team = is_team
        self.should_pull_repo_flag = should_pull_repo_flag


    def process_repos(self, submission_folder_name,
                      assignment_code, deadline, student_whitelist=None, should_pull=True):
        """
        This is the core function that will automate the download of
        student submissions.

        There is a sister function called _process_team_repos that focuses
        on teams that is executed after this code. The logic contained
        here mostly applies to both set of submissions.

        Arguments:
          submission_folder_name:   (str) This is the directory for all
            submissions that we will download. This must exist and will throw
            an IOError if it does not exist.

          assignment_code:   (str) This is the two letter name for the
            assignment.

          deadline:   (str) This is the deadline of the assignment if it is
            late. The input must be in strict ISO 8601 format
            'YYYY-MM-DDTHH:MM:SS'. As python 2 does NOT natively support
            different timezones, this must be in UTC timezone to be correctly
            comparable.

          student_whitelist:   (list of str) This is the list of student
            username IDs that we will whitelist. That is to say all students
            in the list will not be ignored. If set to None or empty list,
            we will grab all students.

        """


        result = re.match(self.REGEX_PATTERN, deadline)
        if result is None:
            str_buffer = (
              "%s: input deadline is not a properly formatted ISO 8601 date\n"
              "Please enter it as 'YYYY-MM-DDTHH:MM:SS'\n"
              "Don't forget to convert that to UTC time has Python 2.X does "
              " not natively support it."
            )
            print(str_buffer % inspect.currentframe().f_code.co_name)

            return


        assignment_alias = submission_folder_name.split('/')[-1]

        if not os.path.isdir(self.MAIN_REPO_DIR):
            os.makedirs(self.MAIN_REPO_DIR)

        if not os.path.isdir(submission_folder_name):

            raise IOError(
              ("%s: Submission folder name '%s' not found. "
               "Please download this from T-Square before continuing. "
               "Exiting.") %
              (inspect.currentframe().f_code.co_name, submission_folder_name))


        # Guarantee that we will process something if we have an empty list
        if not student_whitelist:

            student_aliases = self._get_file_dict(
              filename=self.STUDENT_ALIAS_FILENAME,
              caller_name=inspect.currentframe().f_code.co_name)

            student_whitelist = student_aliases.keys() # Get all students


        if self.is_team:
            team_records = self._get_file_dict(
              filename=self.TEAM_RECORDS_FILENAME,
              caller_name=inspect.currentframe().f_code.co_name)

        student_records = self._get_file_dict(
          filename=self.STUDENT_RECORDS_FILENAME,
          caller_name=inspect.currentframe().f_code.co_name,
          epilog="Run create_student_json first.")


        # TSQUARE VERSION
        directory_listing = self._get_student_folders(
          submission_folder_name=submission_folder_name,
          student_whitelist=student_whitelist)


        for folder in directory_listing:

            platform_id = folder.split('(')[1].strip(')')

            current_student = student_records.get(platform_id, {})

            if not current_student:
                continue

            gt_student_id = current_student['gt_id']

            if ((not self.is_team and
                 gt_student_id not in student_whitelist) or
                  (self.is_team and
                   team_records[gt_student_id] not in student_whitelist)
               ):

                continue

            # Checking repeated results on calls to simplify them
            base_directory = self._get_submission_folder(submission_folder_name, folder)
            current_assignment = current_student[assignment_alias] = {}

            current_submission_file = self._get_submission_file_name(current_student, platform_id)

            # TODO: These methods below should be combined together?

            # Update submission text
            self._check_submission_file(
              current_assignment=current_assignment,
              base_directory=base_directory,
              submission_file=current_submission_file,
              current_student=current_student,
              platform_id=platform_id)

            # Update t-square timestamp
            self._set_timestamp_t_square(
              current_assignment=current_assignment,
              base_directory=base_directory)

            # Clone repo if needed
            # NOTE: You'll need to authenticate with Github here and
            # debuggers may not work properly
            self._setup_student_repo(gt_student_id=gt_student_id, should_pull=should_pull)

            # Only check commit ID validity with GitHub timestamp
            if self._is_commit_present(
              commit_status=current_assignment['commitID']):

                # Try to check out commit ID
                self._check_commitID(
                  current_assignment=current_assignment,
                  assignment_code=assignment_code,
                  gt_student_id=gt_student_id)

                self._compare_timestamp_github(
                  current_assignment=current_assignment,
                  gt_student_id=gt_student_id, deadline=deadline)

            # Check T-Square timestamp against deadline
            self._compare_timestamp_t_square(
              current_assignment=current_assignment,
              deadline=deadline)

            # Reset the repo ptr to master if needed
            #repo_suffix = self._get_correct_reference_id(
            #  graded_id=gt_student_id)
            #self._execute_command(
            #  'cd %s; git checkout master &> /dev/null' %
            #  self._gen_prefixed_dir(prefix_str=repo_suffix))

            # Save Result
            student_records[platform_id] = current_student


        if student_records is not None:

            # Save info
            with open(self.STUDENT_RECORDS_FILENAME, 'w') as output_file:
                json.dump(student_records, output_file)

        if self.is_team and student_whitelist:
            self._process_team_repos(
              assignment_alias=assignment_alias,
              assignment_code=assignment_code,
              student_whitelist=student_whitelist)


        print("\n\n>>>>>%s: complete for '%s'<<<<<\n\n" %
              (inspect.currentframe().f_code.co_name, assignment_code))


    def _process_team_repos(self, assignment_alias, assignment_code,
                            student_whitelist):
        """
        This is the extension process_repos that focuses only on teams.
        As such this should only be called on team repos.

        Arguments:
          assignment_alias:   (str) This is the name of the assignment, i.e.
            the submission name.

          assignment_code:   (str) This is the two letter name for the
            assignment.

          student_whitelist:   (list of str) This is the list of student
            username IDs that we will whitelist. That is to say all students
            in the list will not be ignored. If set to None or empty list,
            we will grab all students.

        """


        student_aliases = self._get_file_dict(
          filename=self.STUDENT_ALIAS_FILENAME,
          caller_name=inspect.currentframe().f_code.co_name)


        student_records = self._get_file_dict(
          filename=self.STUDENT_RECORDS_FILENAME,
          caller_name=inspect.currentframe().f_code.co_name,
          epilog="Run _create_student_json first.")

        team_records = self._get_file_dict(
          filename=self.TEAM_MEMBERS_FILENAME,
          caller_name=inspect.currentframe().f_code.co_name)


        for team in student_whitelist:

            member_list, commit_list = team_records[team], []

            for student in member_list:

                platform_id = student_aliases[student]
                team_assignment = (
                  student_records[platform_id][assignment_alias])

                try:
                    commit_time = team_assignment['Timestamp GitHub']
                    commitID = team_assignment['commitID']

                except KeyError:
                    continue

                if (self._is_commit_present(commit_status=commitID) and
                      commit_time != self.STR_NA):

                    commit_list.append((commit_time, commitID))


            # checkout most recent commit here
            if len(commit_list) > 0:

                # Most recent should be first
                commit_list.sort(reverse=True)
                _, most_recent_commit = commit_list[0]

                command = (
                  'cd %s; git checkout %s &> /dev/null; git tag %s &> /dev/null' % (
                    self._gen_prefixed_dir(team), most_recent_commit,
                    assignment_code))

                _ = self._execute_command(command=command)

            else:
                print("%s: No valid commit for team '%s'!" % (
                  inspect.currentframe().f_code.co_name, team))


    def generate_report(self, assignment, student_list=None,
                        report_filename=None):
        r"""
        This generates the final report that can be used by a grader.

        The result is outputted to a file (report_filename) and to stdout.

        Arguments:
          assignment:   (str) This is the name of the assignment we are
            comparing against.

          student_list:   (list of str) This is a list of students that we
            will analyze and prints the results.

          report_filename:   (str) This is the filename of the report will
            generate, in addition to stdout. To disable this feature, pass in
            None.

        Returns:
        A file, if set, with the results and the output to stdout.
        """


        student_aliases = self._get_file_dict(
          filename=self.STUDENT_ALIAS_FILENAME,
          caller_name=inspect.currentframe().f_code.co_name)

        student_records = self._get_file_dict(
          filename=self.STUDENT_RECORDS_FILENAME,
          caller_name=inspect.currentframe().f_code.co_name,
          epilog="Run process_repos first.")


        bad_commit, late_github, late_submission, missing = [], [], [], []

        _init_log(log_filename=report_filename)
        logger.info("Report: %s\n", assignment)

        if self.is_team:

            team_records = self._get_file_dict(
              filename=self.TEAM_MEMBERS_FILENAME,
              caller_name=inspect.currentframe().f_code.co_name)

            new_student_list = []

            for team in student_list:

                members_list = team_records[team]

                new_student_list.append(team)
                new_student_list.extend(members_list)

            student_list = new_student_list

        elif not student_list:

            student_list = student_aliases.keys() # Get all students

        #else:
          # We are passed a fixed set of students and this is not a team.

        # Parse the student list for bad elements
        stripped_list = map(str.strip, map(str, student_list))
        final_list = list(filter(bool, stripped_list))

        # This is a filter to get bad students in different spots
        bad_student_dict = {
          'Submission GitHub': (self.STR_LATE, late_github),
          'Submission Time': (self.STR_LATE, late_submission),
          'commitID': (self.STR_MISSING, missing),
          'commitID valid': (False, bad_commit)
        }


        for student in final_list:

            if self.is_team and 'Team' in student:
                logger.info("\n========== %s ==========", student)
                continue
            else:
                logger.info(student)

            student_info = student_records[student_aliases[student]]

            if assignment not in student_info:

                logger.info('\tNo records found')
                missing.append(student)
                continue

            student_info_assignment = student_info[assignment]

            for key in sorted(student_info_assignment.keys(), reverse=True):

                student_info_assignment_value = student_info_assignment[key]
                logger.info('\t%s: %s', key, student_info_assignment_value)

                try:
                    target_value, target_list = bad_student_dict[key]
                    if target_value == student_info_assignment_value:
                        target_list.append(student)

                except KeyError:
                    pass


        logger.info("\n========== RESULTS ==========")
        str_buffer = ["\nLATE SUBMISSIONS:"]
        for fmt_str, data in [("\tSubmission (%d): %s", late_submission),
                              ("\tGitHub (%d): %s", late_github),
                              ("\nMISSING SUBMISSIONS (%s): %s", missing),
                              ("\nBAD COMMITS (%s):\n\t%s", bad_commit)]:

            str_buffer.append(fmt_str % (len(data), ", ".join(data)))

        logger.info("\n".join(str_buffer))


    def _setup_student_repo(self, gt_student_id, should_pull=True):
        r"""
        Checks if the student Git repo is downloaded and cleans it up for the
        grader.

        Assignment:
          gt_student_id:   (str) The student ID we will use download the repo.

        """


        just_cloned_repo = None
        repo_suffix = self._get_correct_reference_id(graded_id=gt_student_id)

        if not os.path.isdir(self._gen_prefixed_dir(prefix_str=repo_suffix)):

            command = ('cd %s; '
                       'git clone https://github.gatech.edu/%s/%s%s.git; '
                       'cd ..') % (
                         self.MAIN_REPO_DIR, self.GIT_CONTEXT,
                         self.FOLDER_PREFIX, repo_suffix)
            _ = self._execute_command(command=command)

            self.cached_teams_pulled.add(repo_suffix)
            just_cloned_repo = True

        else:

            just_cloned_repo = False


        # Revert any local changes and pull from remote
        try:

            pull_flag = ''

            if self._should_pull_repo(repo_suffix, should_pull) or just_cloned_repo:

                pull_flag = 'git pull; '

            command = (
              ('cd %s; %s'
               'git reset --hard; cd - &> /dev/null') % (
                 self._gen_prefixed_dir(prefix_str=repo_suffix), pull_flag))

            _ = self._execute_command(command=command)


        # TODO: Unneeded?
        except subprocess.CalledProcessError as error:

            try:
                print("%s: student '%s' subprocess.CalledProcessError: %s\n" % (
                  inspect.currentframe().f_code.co_name,
                  gt_student_id, str(error.output)))

            except UnicodeDecodeError:
                print(("%s: student '%s' subprocess.CalledProcessError: "
                       "UnicodeDecodeError\n") % (
                         inspect.currentframe().f_code.co_name, gt_student_id))


    def _execute_command(self, command):
        r"""
        Parses the command, if it is executed on Windows and returns the output.

        Arguments:
          command:   (str) The command we will execute and return the result.

        Return:
        The command's output.
        """


        if self.OS_TYPE == 'Windows':

            # Windows chains commands with &, *nix with ;
            command = command.replace('&> /dev/null', '')
            command = command.replace(';', '&')

            # Windows doesn't support 'go back to last directory'
            command = command.replace('& cd -', '')

        raw_info = subprocess.check_output(command, shell=True).strip()
        info = raw_info.decode(self.ENCODING)

        return info


    def create_student_json(self, input_filename, should_create_json_files=False):
        r"""
        Converts the input file to two useful JSON files specifically
        for student grading.

        Arguments:
          input_filename:   (str) The input filename we will parse into JSON
            files.
          should_create_json_files: (bool) whether or not we should create these files. Defaults to false.

        """

        if should_create_json_files:
            try:

                with open(input_filename, 'r') as input_file:

                    gt_id_dict, student_records = {}, {}

                    for line in input_file:

                        parsed_line = line.strip().split('\t')

                        try:
                            if self.PLATFORM == "TSQUARE":
                                name, gt_id, platform_id = parsed_line[0:3]
                            elif self.PLATFORM == "CANVAS":
                                name, platform_id, gt_id = parsed_line[0:3]
                            else:
                                raise TypeError("create_student_json error! Currently selected platform %s isn't supported yet! Valid platforms are %s" % (self.PLATFORM, self.PLATFORMS_VALID))
                        except ValueError:
                            print("Malformed input not added: %s" % str(parsed_line))
                            continue # just skip malformed input

                        student_records[platform_id] = {
                          'name': name, 'gt_id': gt_id}
                        gt_id_dict[gt_id] = platform_id

            except IOError:
                raise IOError(
                  "%s: Missing file '%s'. Exiting." % (
                    inspect.currentframe().f_code.co_name, input_filename))


            with open(self.STUDENT_RECORDS_FILENAME, 'w') as output_file:
                json.dump(student_records, output_file)
            with open(self.STUDENT_ALIAS_FILENAME, 'w') as alias_file:
                json.dump(gt_id_dict, alias_file)


    def _get_correct_reference_id(self, graded_id):
        r"""
        Depending on which submission type, converts it to the correct ID
        instance so we can access the appropriate repo.

        For non-team projects, the ID is the correct student ID.
        For team projects, we convert said student into the correct team ID>

        Arguments:
          graded_id:   (str) The ID we will convert depending on the mode.

        Return:
        The corrected ID.
        """


        if self.is_team:

            team_records = self._get_file_dict(
              filename=self.TEAM_RECORDS_FILENAME,
              caller_name=inspect.currentframe().f_code.co_name)

            try:
                team_id = team_records[graded_id]

            except IndexError:
                raise IndexError(
                  "%s: Couldn't find team for student with GTID '%s'. Exiting."
                  % (inspect.currentframe().f_code.co_name, graded_id))

            return team_id

        else:

            # This is the student ID
            return graded_id


    def _get_file_dict(self, filename, caller_name='', epilog=''):
        r"""
        Attempts to access the file and retrieve the JSON within it.

        Arguments:
          filename:   (str) The name of the file we will open.

          caller_name:   (str) This is the caller's function name when
            printing errors.

          epilog:   (str) This is the epilogue error message if one is needed.

        NOTE:
          For Python, JSON and the native Python dictionary are one and the
          same as they have matching calls and very similar syntax.

        Returns:
        The associated JSON (Python Dict) at the file or an IOError.
        """


        file_dict = self.cached_file_dicts.get(filename, None)

        if file_dict is None:

            try:
                with open(filename, 'r') as my_file:
                    file_dict = self.cached_file_dicts[filename] = json.load(my_file)

            except IOError:
                raise IOError(
                  "%s: Missing file '%s'%s Exiting." % (
                    caller_name, filename, epilog))

        return file_dict


    def _get_student_folders(self, submission_folder_name, student_whitelist):
        r"""
        Get a list of student repos that we will grade.

        If student_whitelist is not set, we will grab all student repos.

        Arguments:
          submission_folder_name:   (str) This is the directory for all
            submissions that we will download. This must exist and will throw
            an IOError if it does not exist.

          student_whitelist:   (list of str) This is the list of student
            username IDs that we will whitelist. That is to say all students
            in the list will not be ignored. If set to None or empty list,
            we will grab all students.

        Return:
        A list of all student submissions we will process.
        """


        if not student_whitelist:
            return list(filter(
              os.path.isdir, os.listdir(submission_folder_name)))


        if self.is_team:

            team_records = self._get_file_dict(
              filename=self.TEAM_MEMBERS_FILENAME,
              caller_name=inspect.currentframe().f_code.co_name)

            # Read data in student_whitelist
            student_whitelist_multi_list = [
              team_records[team] for team in student_whitelist]
            # Flatten multi list to be a single list and store it back
            student_whitelist = list(
              itertools.chain.from_iterable(student_whitelist_multi_list))

            # student_whitelist now contains student GTIDs instead of team names

        student_aliases = self._get_file_dict(
          filename=self.STUDENT_ALIAS_FILENAME,
          caller_name=inspect.currentframe().f_code.co_name)

        student_records = self._get_file_dict(
          filename=self.STUDENT_RECORDS_FILENAME,
          caller_name=inspect.currentframe().f_code.co_name,
          epilog="Run _create_student_json first.")

        folders = []


        for student in student_whitelist:

            try:
                platform_id = student_aliases[student]
                name = student_records[platform_id]['name']

            except IndexError:
                logger.error(
                  "Couldn't get folder name for student with GTID %s\n",
                  student)

            folders.append('%s(%s)' % (name, platform_id))

        return folders


    def _gen_prefixed_dir(self, prefix_str):
        r"""
        Combines a directory prefix into the valid directory, to target a
        student's directory.

        Arguments:
          prefix_str:   (str) A valid student's prefix (be it a team number
            or a student name) so we can access it.

        Returns:
        A valid directory that can be accessed.
        """


        return os.path.join(self.MAIN_REPO_DIR, "%s%s" %
                            (self.FOLDER_PREFIX, prefix_str))


    def _check_commitID(self, current_assignment,
                        assignment_code, gt_student_id):
        r"""
        Checks if the current commit is a valid comment in the Repo.

        Some students may submit commits that are invalid.

        The result is stored in current_assignment.

        Arguments:
          current_assignment:   (dict) This is the current assignment we are
          checking the commit of.

          assignment_code:   (str) This is the two letter name for the
            assignment.

          gt_student_id:   (str) This is a student's ID what we will grab
          the info of.

        """


        repo_suffix = self._get_correct_reference_id(graded_id=gt_student_id)

        command = (
          'cd %s; git checkout %s; git tag -f %s &> /dev/null;'
          'git show --pretty=format:\'%%H\' --no-patch; '
          'cd - &> /dev/null' % (
            self._gen_prefixed_dir(prefix_str=repo_suffix),
            current_assignment['commitID'], assignment_code))

        output_checkout = self._execute_command(command=command)

        if self.OS_TYPE == 'Windows':
            # Windows returns \\ prefix and suffix so strip it
            commit = output_checkout[1:-1]
        else:
            commit = str(output_checkout).split('/')[0]  # may have suffix /<path>

        valid_commit = commit == current_assignment['commitID']
        current_assignment['commitID valid'] = valid_commit

    def _get_submission_folder(self, submission_folder_name, folder):
        r"""
        Gets the folder student submissions where student submission info can be found
        :param submission_folder_name: root folder for all submissions for this assignment
        :param folder: student folder
        :return:
        """

        if self.PLATFORM == "TSQUARE":
            folder_name = os.path.join(submission_folder_name, folder)
        elif self.PLATFORM == "CANVAS":
            folder_name = submission_folder_name
        else:
            raise ValueError("_get_submission_folder does not handle platform %!" % self.PLATFORM)

        return folder_name

    def _get_submission_file_name(self, current_student, platform_id, late=False):
        r"""
        Get the name of the file to pull submission text from.
        :param current_student: GT ID of student
        :param platform_id: student identifier (differs per platform)
        :return:
        """

        if self.PLATFORM == "TSQUARE":
            current_submission_file = (
                    '%s(%s)_submissionText.html' % (
                current_student['name'], platform_id))
        elif self.PLATFORM == "CANVAS":
            name = current_student['name'].replace(",", "").replace(" ", "").lower()

            label = ""
            if late:
                label = "late_"

            current_submission_file = "%s_%s%s_text.html" % (name, label, platform_id)
        else:
            raise ValueError("_get_submission_file_name does not handle platform %!" % self.PLATFORM)

        return current_submission_file

    def _check_submission_file(self, current_assignment,
                               base_directory, submission_file, current_student, platform_id, tried_late=False):
        r"""
        This checks the submission file and see there is a valid commit.

        Arguments:
          current_assignment:   (dict) This is the current assignment we are
            checking the submission of.

          base_directory:   (str) This is the base directory we will read the
            file from.

          submission_file:   (str) This is the submission file we are reading
            from.

        NOTE:
          We not check if the commit exists in the repo or is valid, only if
          there is one. This is left to a different method.
        """

        try:
            with open(os.path.join(base_directory, submission_file), 'r') as submission_info:

                strings = re.findall(r'([0-9A-Za-z]{40})',
                                     submission_info.read())

                commitID = strings[0] if len(strings) else self.STR_INVALID
                current_assignment['commitID'] = commitID

                if self.PLATFORM == "CANVAS" and "_late_" in submission_file:
                    current_assignment['Timestamp Submission'] = self.STR_LATE
                else:
                    current_assignment['Timestamp Submission'] = self.STR_OK

        except IOError:
            if self.PLATFORM == "CANVAS" and not tried_late:
                submission_file = self._get_submission_file_name(current_student, platform_id, late=True)
                self._check_submission_file(current_assignment, base_directory, submission_file, current_student, platform_id, tried_late=True)
            else:
                current_assignment['commitID'] = self.STR_MISSING


    def _set_timestamp_t_square(self, current_assignment, base_directory):
        r"""
        This gets the timestamp and sets it in the current assignment.

        The result is stored in current_assignment.

        Arguments:
          current_assignment:   (dict) This is the current assignment we are
            checking the timestamp of.

          base_directory:   (str) This is the base directory we will read the
            file from.

        """

        if self.PLATFORM == 'TSQUARE':
            try:

                target_filename = os.path.join(base_directory,
                                               self.TIMESTAMP_FILENAME)

                with open(target_filename, 'r') as timestamp_info:

                    timestamp = self._fix_timestamp_t_square(
                      time_str=timestamp_info.read())
                    current_assignment['Timestamp Submission'] = timestamp

            except IOError:

                current_assignment['Timestamp Submission'] = self.STR_MISSING
                #current_assignment['commitID'] = self.STR_MISSING  # don't nuke commit ID if timestamp is missing (fixes issue with Canvas)
        elif self.PLATFORM == "CANVAS":
            pass # this is handled in
        else:
            raise ValueError("_set_timestamp_t_square does not currently handle platform %! Valid platforms are %s" % (self.PLATFORM, self.PLATFORMS_VALID))


    def _compare_timestamp_github(self, current_assignment,
                                  gt_student_id, deadline):
        r"""
        This parses the timestamp on Github and compares it to see if the commit
        is late.

        The result is stored in current_assignment.

        Arguments:
          current_assignment:   (dict) This is the current assignment we are
            checking the timestamp of.

          gt_student_id:   (str) The student ID we will use to get the
            timestamp.

          deadline:   (str) This is the deadline of the assignment if it is
            late. The input must be in strict ISO 8601 format
            'YYYY-MM-DDTHH:MM:SS'. As python 2 does NOT natively support
            different timezones, this must be in UTC timezone to be correctly
            comparable.

        """


        if not current_assignment['commitID valid']:

            current_assignment['Submission GitHub'] = self.STR_NA
            current_assignment['Timestamp GitHub'] = self.STR_NA

        else:

            repo_suffix = self._get_correct_reference_id(
              graded_id=gt_student_id)

            # check timestamp of GitHub commit
            command = (
              'cd %s; git show -s --format=%%cI %s; cd - &> /dev/null' % (
                self._gen_prefixed_dir(prefix_str=repo_suffix),
                current_assignment['commitID']))

            output_timestamp = self._execute_command(command=command)

            dt_object = self._read_strict_ISO_format(time_str=output_timestamp)
            timestamp_github = dt_object.strftime(self.DATETIME_PATTERN)

            # check GitHub timestamp against deadline
            current_assignment['Timestamp GitHub'] = timestamp_github
            msg = self.STR_OK if timestamp_github < deadline else self.STR_LATE
            current_assignment['Submission GitHub'] = msg


    def _compare_timestamp_t_square(self, current_assignment, deadline):
        """
        Compares the T-Square timestamp to see if the commit is late.

        The result is stored in current_assignment.

        Arguments:
          current_assignment:   (dict) This is the current assignment we are
            checking the timestamp of.

          gt_student_id:   (str) The student ID we will use to get the
            timestamp.

          deadline:   (str) This is the deadline of the assignment if it is
            late. The input must be in strict ISO 8601 format
            'YYYY-MM-DDTHH:MM:SS'. As python 2 does NOT natively support
            different timezones, this must be in UTC timezone to be correctly
            comparable.

        """

        if current_assignment['commitID'] != self.STR_MISSING and current_assignment['Timestamp Submission'] != self.STR_MISSING:
            final_time = current_assignment['Timestamp Submission']

            msg = self.STR_OK if final_time <= deadline or final_time == self.STR_OK else self.STR_LATE
            current_assignment['Submission Time'] = msg


    def _fix_timestamp_t_square(self, time_str):
        r"""
        This function guarantees that converting t_square time is done exactly
        one so multiple calls won't accidentally convert it twice.

        Arguments:
          time_str:   (str) The input string that may or may not be correct.

        Returns:
        The date formatted in strict ISO 8601 format as a string.

        NOTE:
          T-square time is one long "int" formatted as:
            > 20171006031150569
              YYYYMMDDHHMMSSSSS
          We want to convert to strict ISO 8601 for easier comparision.
            > 2017-10-06T03:11:50 569
              YYYY-MM-DDTHH:MM:SS ---

        """


        new_time_str = None

        try:
            _ = int(time_str)

        except ValueError:
            new_time_str = time_str

        else:
            new_time_str = (
              datetime.strptime(time_str[:14],
                                self.T_SQUARE_DATETIME_PATTERN).isoformat())

        return new_time_str


    def _is_commit_present(self, commit_status):
        r"""
        Checks if the commit statue message states it is present.

        Arguments:
          commit_status:   (str) The current commit status.

        Returns:
        True if it's not a bad commit or False if it is.
        """


        return commit_status not in self.BAD_STR_LIST


    def _read_strict_ISO_format(self, time_str):
        r"""
        Reads in a strict ISO 8601 format date with the timezone and returns
        back the assocated time object.

        This matches GIT's "%cI" date format.

        Arguments:
        time_str:   (str) The ISO 8601 strict date format as a string.

        Returns:
        A correct datetime object with the date
        """

        time_str = time_str.split("/")[0]  # may have suffix /<path>

        time_obj = datetime.strptime(time_str[:19], self.DATETIME_PATTERN)
        positive_sign = hour = minute = 0

        try:
            positive_sign = 0 if time_str[20] == '-' else 1
            hour, minute = map(int, time_str[21:].split(':'))

        except IndexError:
            pass

        if positive_sign:
            return time_obj + timedelta(hours=hour, minutes=minute)
        else:
            return time_obj - timedelta(hours=hour, minutes=minute)


    def _should_pull_repo(self, team_number, should_pull=True):
        r"""
        Checks if we should pull a repo or assume it has been pulled already.

        This is only applicable for team projects as multiple students work
        on the same repo.

        Arguments:
          team_number:   (str or any key) This is the team number we will
          check to see if we pull a repo. For non-teams, we should always pull.

        Return:
        A boolean saying if the repo should be pulled.
        """


        if not self.should_pull_repo_flag:
            return False

        if self.is_team:

            if team_number in self.cached_teams_pulled:
                should_pull = False

            self.cached_teams_pulled.add(team_number)

        return should_pull


def _init_log(log_filename=None, log_file_mode='w', fmt_str=None):
    r"""
    Initializes the logging for this module.

    This should not be in a class as this is unique per file (module) nor
    should be this imported. Moreover, the class needs to have logger imports
    on the new file, if moved. This can be called multiple times and will
    clear all current logs and make new ones.

    Arguments:
      log_filename:   (str) This is the log filename we are outputting to.
        None will disable this and empty string will use the default name,
        "submission_runner.txt".

      log_file_mode:   (str) This sets the file bit for the output file.

        'w':  Overwrite (aka clobber the file)

        'a':  Append (aka add to the end of the file)

        Other commands may exist as this is similar to the second argument
          in open.

      fmt_str:   (str) This is the format string used for the logger,
        default if set to None or empty string is just the message.

        Be mindful that this shows up in very message printed.
        An example is included to showcase what can be done.

    WARNING:
      If this is called multiple times, stdout will get multiple copies of any
      logger call, which will create repeating lines.

    """


    # Checking for Falsy doesn't work since "" and None are similar.
    if log_filename == "":
        log_filename = 'submission_runner.txt'

    if fmt_str is None or not fmt_str:
        fmt_str = "%(message)s"
        # Enable for more timing info
        #fmt_str="%(asctime)s - %(name)30s - %(levelname)10s: %(message)s"

    fmt_str = logging.Formatter(fmt_str)
    logger.setLevel(logging.DEBUG)

    logger.handlers = [] # Clear all old handlers

    stdout = logging.StreamHandler()
    stdout.setFormatter(fmt_str)
    stdout.setLevel(logging.INFO)
    logger.addHandler(stdout)

    if log_filename is not None:
        fout = logging.FileHandler(filename=log_filename, mode=log_file_mode)
        fout.setFormatter(fmt_str)
        fout.setLevel(logging.DEBUG)
        logger.addHandler(fout)

