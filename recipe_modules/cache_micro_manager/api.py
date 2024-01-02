from datetime import datetime
from datetime import timedelta
import json

from recipe_engine import recipe_api

JSON_ENTRY_NAME = 'name'
JSON_ENTRY_UPDATED_DATE = 'updated_date'
JSON_ENTRY_REMOVAL_DATE = 'removal_date'

PACKAGE_REMOVAL_INTERVAL_DAYS = 30


class CacheEntry:
  """An object used to represent a file and its usage in a cache."""

  def __init__(
      self,
      file_name,
      updated_date: datetime = None,
      removal_date: datetime = None,
  ):
    self.name = file_name

    # The updated date will be stored as a string for easy conversion to and from json.
    self.updated_date = updated_date
    self.updated_date = updated_date.strftime("%m/%d/%Y, %H:%M:%S")

    # The removal date will be stored as a string for easy conversion to and from json.
    self.removal_date = removal_date
    if self.removal_date is None:
      self._calc_removal_date(self.updated_date)
    else:
      self.removal_date = removal_date.strftime("%m/%d/%Y, %H:%M:%S")

  def _calc_removal_date(self, updated_date: datetime):
    """Calculate the removal date as the update date + 30 days."""
    time_delta = timedelta(days=PACKAGE_REMOVAL_INTERVAL_DAYS)
    updated_date_datetime = datetime.strptime(
        updated_date, "%m/%d/%Y, %H:%M:%S"
    )
    new_removal_date = updated_date_datetime + time_delta
    self.removal_date = new_removal_date.strftime("%m/%d/%Y, %H:%M:%S")

  def removal_date_as_datetime(self) -> datetime:
    """Return the stored removal timestamp string as a datetime object."""
    return self._convert_str_to_datetime(self.removal_date)

  def _convert_str_to_datetime(self, date_str: str) -> datetime:
    """Return the converted string date as a datetime object"""
    return datetime.strptime(date_str, "%m/%d/%Y, %H:%M:%S")


class CacheMicroManagerApi(recipe_api.RecipeApi):
  """This module keeps track of root individual files within a directory (based on
  a non-recursivce mode). It keeps track of the last time a file was used and
  proactively cleans the directory by removing files older than some specified time.
  """

  # pylint: disable=unused-argument
  def __init__(self, *args, **kwargs):
    """Create a new CacheMicroManager object.

    Args:
      target_dir (str): the path to the cache directory containing dependencies.
    """
    super(CacheMicroManagerApi, self).__init__(*args, **kwargs)
    self.cache_target_directory = None
    self.cache_name = None
    self.metadata_file_name = None
    self.cache_metadata_file_path = None

  def _initialize(self, target_dir):
    self.cache_target_directory = target_dir
    self.cache_name = self.m.path.basename(self.cache_target_directory)
    self.metadata_file_name = '.{}_cache_metadata.json'.format(self.cache_name)
    self.cache_metadata_file_path = self.cache_target_directory.join(
        self.metadata_file_name
    )

  def today(self):
    return datetime.now()  # pragma: nocover

  def run(self, target_dir, deps_list: list):
    """Run the cache micro manager on the target directory.

    If the directory is not yet being tracked by the cache micro manager it will read the contents of
    the target_dir_path and all current files and directories to cache metadata file.

    If the directory is being tracked it will add any dependencies in deps_list not present in the file
    to the metadata file or update the updated and removal date of dependencies in deps_list in the file.

    After the deps are updated or added it will perform the following minor cleanup:
    * If there is an entry in the metadata file but the package is not on disk it will remove the entry
    from the file.
    * If there is a package on disk but not in the file it will simply add it to the metadata file for
    tracking and eventual removal.
    * Then it will look at all removal dates from the metadata file and delete all expired packages from
    disk and remove them from the metadata file.

    Args:
      * deps_list(list[str]): the list of dependencies that are currently being used.
    """
    self._initialize(target_dir=target_dir)

    with self.m.step.nest('Running Cache Micro Manager on {}.'.format(
        self.cache_target_directory)):
      if not self.m.path.exists(self.cache_metadata_file_path):

        # this returns the singular file names not full paths.
        directory_files_list = self.m.file.listdir(
            'Reading cache directory {}'.format(self.cache_target_directory),
            self.cache_target_directory,
            recursive=False,
        )

        directory_cache_entry_list = self.convert_file_list_to_cache_entry_list(
            directory_files_list
        )

        if len(directory_cache_entry_list) > 0:
          # It should be safe to ignore the check for existence of the file since no one
          # actively logs onto the bots and manipulates the file system.
          self.m.file.write_text(
              'Writing cache metadata file.',
              self.cache_metadata_file_path,
              json.dumps([ob.__dict__ for ob in directory_cache_entry_list]),
          )
      else:
        # the currently stored metadata entries.

        # example of the data that is stored in the metadata file.
        # [
        #   {
        #     "name": "package_1",
        #     "updated_date": "datetime",
        #     "removal_date": "datetime + interval"
        #   },
        #   {
        #     "name": "package_2",
        #     "updated_date": "datetime",
        #     "removal_date": "datetime + interval"
        #   }
        # ]

        current_metadata_entries = self.read_metadata_file()

        # these files may not be in the metadata file, no telling how they got there.
        # This returns Path objects.
        current_directory_entries = self.m.file.listdir(
            'Reading cache directory {}'.format(self.cache_target_directory),
            self.cache_target_directory, False
        )
        current_directory_entries.remove(self.cache_metadata_file_path)

        # add or update the current working dependencies.
        for dep in deps_list:
          if not self.is_file_name_in_cache_entry_list(
              dep, current_metadata_entries):
            # we need to add it.
            current_metadata_entries.append(
                CacheEntry(file_name=dep, updated_date=self.today())
            )
          else:
            # we want to update it.
            existing_entry = self.get_cache_entry_from_list(
                dep, current_metadata_entries
            )
            # package will be active for another month.
            new_entry = CacheEntry(
                file_name=existing_entry.name, updated_date=self.today()
            )
            current_metadata_entries.remove(existing_entry)
            current_metadata_entries.append(new_entry)

        # there can be deps in the file and not in the directory or
        for current_meta_entry in current_metadata_entries:
          if self.m.path.abspath(current_meta_entry.name) not in [
              self.m.path.abspath(item) for item in current_directory_entries
          ]:
            current_metadata_entries.remove(current_meta_entry)

        # there can be deps in the directory and not in the file.
        for file_name_str in current_directory_entries:
          cacheEntry = self.get_cache_entry_from_list(
              file_name_str, current_metadata_entries
          )
          if cacheEntry is None:
            current_metadata_entries.append(
                CacheEntry(
                    file_name=self.m.path.abspath(file_name_str),
                    updated_date=self.today()
                )
            )

        # Check dates and delete unused packages.
        for cacheEntry in current_metadata_entries:
          today = self.today()
          if cacheEntry.removal_date_as_datetime().date() < today.date():
            self.delete_file(cacheEntry.name)
            current_metadata_entries.remove(cacheEntry)

        # write the new file contents.
        self.m.file.remove(
            'Removing existing cache file {}'.format(
                self.cache_metadata_file_path
            ), self.cache_metadata_file_path
        )
        self.m.file.write_text(
            'Writing cache metadata file.',
            self.cache_metadata_file_path,
            json.dumps([ob.__dict__ for ob in current_metadata_entries]),
        )

  def get_cache_entry_from_list(
      self, file_name, cache_entry_list: list
  ) -> CacheEntry:
    """Get the associated cache entry when supplied with a specific file name.

    Args:
      * file_name (str): the name of a file/directory that represents a dependency.
      * cache_entry_list (list[CacheEntry]): a list of CacheEntry objects.

    Returns:
      CacheEntry | None: Returns a CacheEntry if found in the list otherwise returns None.
    """
    for cache_entry in cache_entry_list:
      if self.m.path.abspath(file_name) == self.m.path.abspath(cache_entry.name
                                                              ):
        return cache_entry
    return None

  # file name is a path as passed in here
  def is_file_name_in_cache_entry_list(
      self, file_name, cache_entry_list: list
  ) -> bool:
    """Check to see if a CacheEntry is in the list for the supplied file_name.

    Args:
      * file_name (str): the name of a file/directory that represents a dependency.
      * cache_entry_list (list[CacheEntry]): a list of CacheEntry objects.

    Returns:
      bool: True if a cache entry exists with file_name as its name, False if it does not.
    """
    for cache_entry in cache_entry_list:
      if self.m.path.abspath(file_name) == self.m.path.abspath(cache_entry.name
                                                              ):
        return True
    return False

  def convert_file_list_to_cache_entry_list(
      self, file_names_list: list
  ) -> list:
    """Create a list of CacheEntry objects from a list of file names.

    The primary usage of this is on start of CacheMicroManager when it has not yet begun
    to manage a directory and we need to record the contents of it.

    Args:
      * file_names_list (list[str]): a list of file names to use to instantiate CacheEntry
        objects.

    Returns:
      list[CacheEntry]: a list of newly instantiated CacheEntry objects associate with the
        supplied file names list.
    """
    cache_entry_list = []
    for fd in file_names_list:
      cache_entry = CacheEntry(
          file_name=self.m.path.abspath(fd), updated_date=self.today()
      )
      cache_entry_list.append(cache_entry)
    return cache_entry_list

  def delete_file(self, file_name):
    """Delete a file or directory.

    Args:
      * file_name (Path): a file or directory name that will be deleted.
    """
    try:
      if self.m.path.isfile(file_name):
        self.m.file.remove(
            'Removing file descriptor {}'.format(file_name), file_name
        )  #pragma: nocover
      elif self.m.path.isdir(file_name):
        try:  #pragma: nocover
          self.m.file.rmtree(
              'Removig dir file descriptor {} (rmtree)'.format(file_name),
              file_name
          )  #pragma: nocover
        except:  #pragma: nocover
          self.m.step(
              'Removing dir file descriptor {} (fallback rm)'.format(file_name),
              ['rm', '-rf', file_name]
          )  #pragma: nocover
    except self.m.file.Error:  #pragma: nocover
      print('File not found.')  #pragma: nocover

  def read_metadata_file(self) -> list:
    """Read the metadata file at the self.cache_metadata_file_location path.

    Returns:
      list[CacheEntry]: returns the list of CacheEntry's found in the existing file.
    """
    with self.m.step.nest('Reading metadata file {}'.format(
        self.cache_metadata_file_path)):
      # it is possible to return an empty list, populated list or None.
      meta_json = self.m.file.read_text(
          'Reading {}'.format(self.cache_metadata_file_path),
          self.cache_metadata_file_path,
      )
      meta_cache_entries = []
      json_items = json.loads(meta_json)
      for item in json_items:
        # TODO(ricardoamador) remove this code once the old dates without times are removed.
        updated_date_found = None
        if (self.date_format_check(item[JSON_ENTRY_UPDATED_DATE])):
          updated_date_found = datetime.strptime(
              item[JSON_ENTRY_UPDATED_DATE], "%m/%d/%Y, %H:%M:%S"
          )
        else:
          updated_date_found = datetime.strptime(
              "{}, 12:00:00".format(item[JSON_ENTRY_UPDATED_DATE]),
              "%m/%d/%Y, %H:%M:%S"
          )

        removal_date_found = None
        if (self.date_format_check(item[JSON_ENTRY_REMOVAL_DATE])):
          removal_date_found = datetime.strptime(
              item[JSON_ENTRY_REMOVAL_DATE], "%m/%d/%Y, %H:%M:%S"
          )
        else:
          removal_date_found = datetime.strptime(
              "{}, 12:00:00".format(item[JSON_ENTRY_REMOVAL_DATE]),
              "%m/%d/%Y, %H:%M:%S"
          )

        new_entry = CacheEntry(
            file_name=item[JSON_ENTRY_NAME],
            updated_date=updated_date_found,
            removal_date=removal_date_found
        )
        meta_cache_entries.append(new_entry)
      return meta_cache_entries

  def date_format_check(self, date_str: str) -> bool:
    """Check the date format of the date we are attempting to process.

    returns:
      True if the time stamp includes the time and the date. False if it only includes the date.
    """
    try:
      datetime.strptime(date_str, "%m/%d/%Y, %H:%M:%S")
      return True
    except ValueError:
      return False
