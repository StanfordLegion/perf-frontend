#!/usr/bin/env python

# Copyright 2017 Stanford University
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from __future__ import print_function
import argparse, collections, datetime, json, os, shutil, subprocess, sys, tempfile

# ksmurthy 2017
import smtplib
from collections import namedtuple
from string import Template
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import numpy
import getpass
import re
data_per_branch_per_application = namedtuple("data_per_branch_per_application",
                                             ["branch", "commit", "date", "timing", "appArg"])
MY_ADDRESS = 'ksmurthy@stanford.edu'
PASSWORD = ''
authorsAndMessages = set()
specialRunOnlyOnceWhy = set()
branchNotFound = set()
GLOBAL_Start_Date = datetime.datetime.min
GLOBAL_End_Date = datetime.datetime.min
finalSetOfEmails = {}
nameEmail = {}
# ksmurthy

_version = sys.version_info.major

if _version == 2:  # Python 2.x:
    def _glob(path):
        def visit(result, dirname, filenames):
            for filename in filenames:
                result.append(os.path.join(dirname, filename))

        result = []
        os.path.walk(path, visit, result)
        return result
elif _version == 3:  # Python 3.x:
    def _glob(path):
        return [os.path.join(dirname, filename)
                for dirname, _, filenames in os.walk(path)
                for filename in filenames]
else:
    raise Exception('Incompatible Python version')


def get_measurements(repo_url):
    tmp_dir = tempfile.mkdtemp()
    try:
        print(tmp_dir)
        subprocess.check_call(
            ['git', 'clone', repo_url, 'measurements'],
            cwd=tmp_dir)
        measurements_dir = os.path.join(tmp_dir, 'measurements', 'measurements')
        print(measurements_dir)
        measurements_paths = [path for path in _glob(measurements_dir)
                              if os.path.splitext(path)[1] == '.json']
        measurements = []
        for path in measurements_paths:
            with open(path) as f:
                measurements.append((path, json.load(f)))
        return measurements
    finally:
        shutil.rmtree(tmp_dir)


def extract_measurements(measurements):
    branches = set()
    commit_date = {}
    commits_by_branch = collections.defaultdict(lambda: set())
    measurements_by_commit = collections.defaultdict(lambda: [])
    measurements_by_application = collections.defaultdict(lambda: set())
    for path, measurement in measurements:
        commit = measurement['metadata']['commit']
        branch = measurement['metadata']['branch']
        argv = ' '.join(measurement['metadata']['argv'])
        perfValue = measurement['measurements']['time_seconds']
        perfApplication = measurement['metadata']['benchmark']

        # Reinsert the compact argv into the measurement.
        measurement['metadata']['argv'] = argv

        # Record the branch used.
        branches.add(branch)

        # Record the earliest measurement date for this commit.
        date = datetime.datetime.strptime(
            measurement['metadata']['date'],
            '%Y-%m-%dT%H:%M:%S.%f')
        if commit not in commit_date or date < commit_date[commit]:
            commit_date[commit] = date

        # ksmurthy 2017
        measurements_by_application[perfApplication].add(
            data_per_branch_per_application(branch, commit, date, perfValue, argv))

        # Add the commit to this branch.
        commits_by_branch[branch].add(commit)

        # Record the measurement.
        measurements_by_commit[commit].append(measurement)

    # Sort commits by earliest measurement date.
    commits_by_branch_by_date = dict(
        (branch, sorted(commits, key=lambda x: commit_date[x]))
        for branch, commits in commits_by_branch.items())

    return branches, commits_by_branch_by_date, measurements_by_commit, measurements_by_application


# ksmurthy 2017 processsing per application

# credit: https://codeselfstudy.com/blogs/how-to-calculate-standard-deviation-in-python
def standard_deviation(lst, population=True):
    """Calculates the standard deviation for a list of numbers."""
    num_items = len(lst)
    mean = sum(lst) / num_items
    differences = [x - mean for x in lst]
    sq_differences = [d ** 2 for d in differences]
    ssd = sum(sq_differences)

    # Note: it would be better to return a value and then print it outside
    # the function, but this is just a quick way to print out the values along
    # the way.
    if population is True:
        # print('This is POPULATION standard deviation.')
        variance = ssd / num_items
    else:
        # print('This is SAMPLE standard deviation.')
        variance = ssd / (num_items - 1)
    sd = numpy.sqrt(variance)
    return sd


def process_application_results(applicationResults, branches):
    # random = collections.defaultdict(lambda: set())
    # for each application
    for application in applicationResults.keys():
        all_perf_values = applicationResults[application]
        appArgSet = set()
        #gather unique arguments to the app, the commit might pass some args but not all
        for x in all_perf_values:
            appArgSet.add(data_per_branch_per_application._make(x).appArg)
        for branch in branches:
            for appArg in appArgSet:
                # get all the per app per branch entries
                vals_per_branch_per_arg = [entry for entry in all_perf_values
                                           if ((data_per_branch_per_application._make(entry).branch == branch) &
                                                (data_per_branch_per_application._make(entry).appArg == appArg))]
                startDate = datetime.datetime.min
                latest = data_per_branch_per_application(0, 0, 0, 0, 0)
                # get the latest commit
                for entry in vals_per_branch_per_arg:
                    if data_per_branch_per_application._make(entry).date > startDate:
                        startDate = data_per_branch_per_application._make(entry).date
                        latest = data_per_branch_per_application._make(entry)
                #get all the per app per branch per uniq argument, timing values except the latest one TODO TODO TODO
                perfValues = [float(vals_per_branch_per_arg.timing)
                              for vals_per_branch_per_arg in vals_per_branch_per_arg
                              if (data_per_branch_per_application._make(vals_per_branch_per_arg).commit != latest.commit)
                              & (data_per_branch_per_application._make(vals_per_branch_per_arg).date > GLOBAL_Start_Date)
                              & (data_per_branch_per_application._make(vals_per_branch_per_arg).date > GLOBAL_End_Date)]
                #if we have only one number, i.e., latest commit, then this must be a new appl, anyway flag it, TODO
                if(perfValues.__len__() == 0):
                    specialRunOnlyOnceWhy.add(latest)
                else:
                    sdPerfValue = standard_deviation(perfValues)
    		    #print("sd value is %lf\n, comparing it with latest:%s\n" %(sdPerfValue, latest.timing))
		    latest_timing_val = (float)(latest.timing) 
                    #flag the author and commit, if we do not satisfy the result, even a perf gain is flagged
                    if ((latest_timing_val < .95 * sdPerfValue) | (latest_timing_val > 1.05 * sdPerfValue)):
                        authorsAndMessages.add((latest, application, sdPerfValue))
    		    #print("done with the comparison sd value is %lf\n" %(sdPerfValue))


def push_json_file(repo_url, path, value):
    # Try to produce JSON files will that will generate small diffs.
    content = json.dumps(value, indent=0, separators=(',', ':'), sort_keys=True)


def make_charts(measurement_url, start_date, end_date):
    measurements = get_measurements(measurement_url)
    GLOBAL_Start_Date = datetime.datetime.strptime(start_date, "%Y-%m-%dT%H:%M:%S")
    GLOBAL_End_Date = datetime.datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%S")
    print('Got %s measurements start:%s end:%s...' % (len(measurements), GLOBAL_Start_Date, GLOBAL_End_Date))
    branches, commits, measurements, applicationResults = extract_measurements(measurements)

    result = {
        'branches': list(branches),
        'commits': commits,
        'measurements': measurements,
    }

    process_application_results(applicationResults, branches)


def send_email(name, email, message_template):
    # name, email = 'Elliott Slaughter', 'slaughter@cs.stanford.edu'  # read the commit author
    # message_template = "hello, your commit screwed the performance"

    PASSWORD = getpass.getpass()
    # set up the SMTP server
    s = smtplib.SMTP(host='smtp.stanford.edu', port=587)  # could be 25 or 2525
    s.starttls()
    s.login(MY_ADDRESS, PASSWORD)

    # For each contact, send the email:
    # for name, email in zip(names, emails):
    msg = MIMEMultipart()  # create a message
    # add in the actual person name to the message template
    # message = message_template.substitute(PERSON_NAME=name.title())
    # Prints out the message body for our sake
    # print(message)
    # setup the parameters of the message
    msg['From'] = MY_ADDRESS
    msg['To'] = email
    msg['Subject'] = "Latest Commit Performance Regression Results"

    # add in the message body
    msg.attach(MIMEText(message_template, 'plain'))

    # send the message via the server set up earlier.
    # s.send_message(msg)
    # ENABLE ONLY AT THE END,
    s.sendmail(MY_ADDRESS, email, msg.as_string())
    del msg

    # Terminate the SMTP session and close the connection
    s.quit()

def sendOutEmail():

    tmp_dir = "/home/users/ksmurthy/perf-data/test-legion-data" #
    #tmp_dir = tempfile.mkdtemp()
    try:
        print(tmp_dir)
        subprocess.check_call( ['git', 'clone', 'http://github.com/stanfordlegion/legion.git', 'legion'], cwd=tmp_dir)
        commitCheckDir = os.path.join(tmp_dir, 'legion')
        gitShowAuthor = 'show' # --format="%aN <%aE>"'
        # for all authors in author and messages, send out the message
        for entry in authorsAndMessages:
            try:
                commitEntry = entry[0]
                application = entry[1]
                sdTime = entry[2]
                subprocess.check_call(
                    ['git', 'checkout', data_per_branch_per_application._make(commitEntry).branch],
                    cwd=commitCheckDir)
                #using the commit id and git show, we will extract the author name, and email
                commitId = data_per_branch_per_application._make(commitEntry).commit
                details = subprocess.check_output(
                    ['git', gitShowAuthor, commitId],
                    cwd=commitCheckDir)
                email = re.search('%s(.*)%s' % ('<', '>'), details).group(1)
                name = re.search('%s(.*)%s' % ('Author: ', ' <'), details).group(1)
                val = data_per_branch_per_application._make(commitEntry)
                #print("email to %s commit:%s did not clear bar; branch:%s appl:%s time:%s sdTime:%lf"
                #      % (email, commitId, val.branch, application, val.timing, float(sdTime)))
                message_template = "email to %s commit:%s did not clear bar; branch:%s appl:%s time:%s sdTime:%lf" % \
                                   (email, commitId, val.branch, application, val.timing, float(sdTime))
                finalSetOfEmails.setdefault(name, [])
                nameEmail.setdefault(name, [])
                finalSetOfEmails[name].append(message_template)
                nameEmail.setdefault(name, email)
            except subprocess.CalledProcessError:
                branchNotFound.add(commitEntry)
    finally:
        shutil.rmtree(commitCheckDir)
	print("about to send out the emails\n")
    for name in finalSetOfEmails:
        messageTemplate = finalSetOfEmails[name]
        email = nameEmail[name]
        print ("%s name %s email %s messagetempl" %(name, email, messageTemplate))
        #send_email(name, email, message_template)
    send_email("karthik", "ksmurthy@stanford.edu", "hello")

def driver():
    # measurement_url https://github.com/StanfordLegion/perf-data/
    parser = argparse.ArgumentParser(
        description='Render Legion performance charts')
    parser.add_argument('measurement_url', help='measurement repository URL')
    parser.add_argument('start_date', help='begin date for perf analysis: yr-mnth-dayThr:min:s.')
    parser.add_argument('end_date', help='end date for perf analysis: yr-mnth-dayThr:min:s.')
    args = parser.parse_args()
    make_charts(**vars(args))
    sendOutEmail()

if __name__ == '__main__':
    driver()
