## @file SelfDescribingEnvironment.py
# This module contains code that is capable of scanning the source tree for
# files that describe the source and dependencies and acting upon those files.
#
##
# Copyright (c) 2017, Microsoft Corporation
#
# All rights reserved.
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
# INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
##
import os
import ShellEnvironment
import EnvironmentDescriptorFiles as EDF
import logging

ENVIRONMENT_BOOTSTRAP_COMPLETE = False
ENV_STATE = None

class SelfDescribingEnvironment(object):
  def __init__(self, workspace_path, scopes=()):
    super(SelfDescribingEnvironment, self).__init__()

    self.workspace = workspace_path
    self.scopes = scopes + ('global',)

    self.paths = None
    self.extdeps = None

  def gather_env_files(self, ext_strings, base_path):
    # Make sure that the search extension matches easily.
    search_files = tuple(ext_string.lower() for ext_string in ext_strings)

    # Walk all of the directories under base_path and find all files
    # matching the extension.
    matches = {}
    for root, dirs, files in os.walk(base_path, topdown=True):
      # Check to see whether any of these directories should be skipped.
      # TODO: Allow these to be passed in via arguments.
      for index, dir in enumerate(dirs):
        if dir == '.git':
          del dirs[index]

      # Check for any files that match the extensions we're looking for.
      for file in files:
        for search_file in search_files:
          if file.lower().endswith(search_file+".json"):
            if search_file in matches:
              matches[search_file].append(os.path.join(root, file))
            else:
              matches[search_file] = [os.path.join(root, file)]

    return matches

  def load_workspace(self):
    logging.debug("--- SelfDescribingEnvironment.load_workspace()")
    logging.debug("Loading workspace: %s" % self.workspace)
    logging.debug("  Including scopes: %s" % ', '.join(self.scopes))

    #
    # First, we need to get all of the files that describe our environment.
    #
    env_files = self.gather_env_files(('path_env', 'ext_dep'), self.workspace)

    #
    # Now that the files have been found, load them, sort them, and filter them
    # so they can be applied to the environment.
    #
    if 'path_env' in env_files:
      all_path_descriptors = tuple(EDF.PathEnvDescriptor(env_file).descriptor_contents for env_file in env_files['path_env'])
      
      # Now, filter and sort based on the available scopes.
      self.paths = ()
      for scope in self.scopes:
        self.paths = self.paths + tuple(pd for pd in all_path_descriptors if pd['scope'].lower() == scope.lower())

    if 'ext_dep' in env_files:
      all_extdep_descriptors = tuple(EDF.ExternDepDescriptor(env_file).descriptor_contents for env_file in env_files['ext_dep'])

      # Now, filter and sort based on the available scopes.
      self.extdeps = ()
      for scope in self.scopes:
        self.extdeps = self.extdeps + tuple(edd for edd in all_extdep_descriptors if edd['scope'].lower() == scope.lower())

    return self

  # This is a generator to reduce code duplication when wrapping the pathenv objects.
  def _get_paths(self):
    if self.paths is not None:
      # Apply in reverse order to get the expected hierarchy.
      for path_descriptor in reversed(self.paths):
        # Use the helper factory to get an object
        # capable of managing each dependency.
        yield EDF.PathEnv(path_descriptor)

  # This is a generator to reduce code duplication when wrapping the extdep objects.
  def _get_extdeps(self):
    if self.extdeps is not None:
      # Apply in reverse order to get the expected hierarchy.
      for extdep_descriptor in reversed(self.extdeps):
        # Use the helper factory to get an object
        # capable of managing each dependency.
        yield ExternalDependencies.ExtDepFactory(extdep_descriptor)

  def _apply_descriptor_object_to_env(self, desc_object, env_object):
    # Walk through each possible environment modification
    # and apply to the environment as required.
    if 'set_path' in desc_object.flags:
      env_object.insert_path(desc_object.published_path)
    if 'set_pypath' in desc_object.flags:
      env_object.insert_pypath(desc_object.published_path)
    if 'set_build_var' in desc_object.flags:
      env_object.set_build_var(desc_object.var_name, desc_object.published_path)
    if 'set_shell_var' in desc_object.flags:
      env_object.set_shell_var(desc_object.var_name, desc_object.published_path)

  def update_simple_paths(self, env_object):
    logging.debug("--- SelfDescribingEnvironment.update_simple_paths()")
    for path in self._get_paths():
      self._apply_descriptor_object_to_env(path, env_object)

  def update_extdep_paths(self, env_object):
    logging.debug("--- SelfDescribingEnvironment.update_extdep_paths()")
    for extdep in self._get_extdeps():
      self._apply_descriptor_object_to_env(extdep, env_object)

  def update_extdeps(self, env_object):
    logging.debug("--- SelfDescribingEnvironment.update_extdeps()")
    for extdep in self._get_extdeps():
      # Check to see whether it's necessary to fetch the files.
      if not extdep.verify():
        extdep.clean()
        extdep.fetch()

      # Process any associated flags and add download to path
      # if needed.
      # if extdep.flags is not None:
      #   self._apply_descriptor_object_to_env(extdep, env_object)

  def clean_extdeps(self, env_object):
    for extdep in self._get_extdeps():
      extdep.clean()
      # TODO: Determine whether we want to update the env.

  def verify_extdeps(self, env_object):
    result = True
    for extdep in self._get_extdeps():
      if not extdep.verify():
        result = False
        logging.info("Dependency '%s' is not met!" % extdep.name)

    return result


def BootstrapEnvironment(workspace, scopes=()):
  global ENVIRONMENT_BOOTSTRAP_COMPLETE, ENV_STATE

  if not ENVIRONMENT_BOOTSTRAP_COMPLETE:
    #
    # ENVIRONMENT BOOTSTRAP STAGE 1
    # Locate and load all environment description files.
    #
    build_env = SelfDescribingEnvironment(workspace, scopes).load_workspace()

    #
    # ENVIRONMENT BOOTSTRAP STAGE 2
    # Parse all of the PATH-related descriptor files to make sure that
    # any required tools or Python modules are now available.
    #
    shell_env = ShellEnvironment.GetEnvironment()
    build_env.update_simple_paths(shell_env)

    #
    # ENVIRONMENT BOOTSTRAP STAGE 3
    # Now that the preliminary paths have been loaded,
    # we can load the modules that had greater dependencies.
    #
    global ExternalDependencies
    import ExternalDependencies
    build_env.update_extdep_paths(shell_env)

    # Debug the environment that was produced.
    shell_env.log_environment()

    ENVIRONMENT_BOOTSTRAP_COMPLETE = True
    ENV_STATE = (build_env, shell_env)

  # Return the environment as it's configured.
  return ENV_STATE


def CleanEnvironment(workspace, scopes=()):
  # Bootstrap the environment.
  (build_env, shell_env) = BootstrapEnvironment(workspace, scopes)

  # Clean all the dependencies.
  build_env.clean_extdeps(shell_env)


def UpdateDependencies(workspace, scopes=()):
  # Bootstrap the environment.
  (build_env, shell_env) = BootstrapEnvironment(workspace, scopes)

  # Clean all the dependencies.
  build_env.update_extdeps(shell_env)


def VerifyEnvironment(workspace, scopes=()):
  # Bootstrap the environment.
  (build_env, shell_env) = BootstrapEnvironment(workspace, scopes)

  # Clean all the dependencies.
  return build_env.verify_extdeps(shell_env)


if __name__ == "__main__":
  # For testing, make some assumptions about where this file is still located.
  base_path = os.path.dirname(os.path.abspath(__file__))
  base_path = os.path.dirname(base_path)
  base_path = os.path.dirname(base_path)
  base_path = os.path.dirname(base_path)

  # For testing, pick a project to use as the scope.
  test_scope = ('ivanhoe',)

  # Clean the environment.
  CleanEnvironment(base_path, test_scope)

  # Update the environment.
  UpdateDependencies(base_path, test_scope)

  # Verify the environment.
  VerifyEnvironment(base_path, test_scope)