import csv
import re
import time
from sys import stderr

from django.utils.text import camel_case_to_spaces

from arcutils.colorize import printer

from ..neighborhoods.models import Neighborhood
from .models import *  # noqa


# Map of CSV field names => model field names.
FIELD_NAME_MAP = {
    'Name in BES Reports': 'name',
    'Project': '',
    'Address': '',
    'Address (Obscured)': '',
    'Address_Clean': '',
    'Watershed': '',
    'Building Use': '',
    'Solar over Ecoroof': '',
    'Type': '',
    'Year': 'year_built',
    'Size (sf)': 'square_footage',
    'Number': '',
    'Latitude(Non Obscured)': 'latitude',
    'Longitude (Non Obscured)': 'longitude',
    'Confidence (Non Obscured)': 'confidence',
    'Latitude': 'latitude_obscured',
    'Longitude': 'longitude_obscured',
    'Confidence': 'confidence_obscured',
    'Depth': '',
    'Cost': '',
    'Composition': '',
    'Irrigation': '',
    'Drainage': '',
    'Plants': '',
    'Maintenance': '',
    'Contractor': '',
}


class CSVDictReader(csv.DictReader):

    @property
    def fieldnames(self):
        names = super().fieldnames
        for i, name in enumerate(names):
            names[i] = FIELD_NAME_MAP.get(name) or self.clean_field_name(name)
        for name in names:
            assert name.isidentifier(), '%s must be a valid identifier' % name
        return names

    def clean_field_name(self, name):
        name = name.lower()
        name = re.sub(r'[^a-z0-9_\s]', '', name)
        name = re.sub(r'\s+', '_', name)
        return name

    def iter_rows(self):
        for row in iter(self):
            row = {k: (v.strip() or None) for (k, v) in row.items()}
            yield row


class Importer:

    """Import locations and related data from CSV file.

    Args:
        file_name: Path to CSV file

    """

    def __init__(self, file_name, overwrite=False, dry_run=False, quiet=False):
        self.file_name = file_name
        self.overwrite = overwrite
        self.dry_run = dry_run
        self.real_run = not dry_run
        self.quiet = quiet

    def print(self, *args, **kwargs):
        if not self.quiet:
            if self.dry_run:
                args = ('[DRY RUN]',) + args
            print(*args, **kwargs)

    def run(self):
        if Neighborhood.objects.count() == 0:
            printer.warning('WARNING: Neighborhoods have not been imported.', file=stderr)
        if self.overwrite:
            self.do_overwrite()
        elif Location.objects.count():
            printer.warning('Importing locations without removing existing records.', file=stderr)
            printer.warning('This will likely FAIL due to duplicate key violations.', file=stderr)
            time.sleep(5)
        data = self.read_data()
        self.column_to_table(data, BuildingUse)
        self.column_to_table(data, Watershed)
        self.insert_locations(data)

    def do_overwrite(self):
        self.print('Removing existing locations...')
        if self.real_run:
            Location.objects.all().delete()
        self.print('Removing existing watersheds...')
        if self.real_run:
            Watershed.objects.all().delete()

    def read_data(self):
        with open(self.file_name) as fp:
            reader = CSVDictReader(fp)
            data = list(reader.iter_rows())
        return data

    def normalize_name(self, name):
        # Convert name to title case if it doesn't already appear to be
        # title-cased.
        return name.title() if name[0].islower() else name

    def choice(self, row, field, choices, null=False):
        value = row[field]
        if value is None:
            if null:
                return None
            raise ValueError('Expected a value for {field} in {row}'.format_map(locals()))
        value = self.normalize_name(value)
        try:
            value = choices[value]
        except KeyError:
            raise ValueError(
                '{value} is not one of the available choices for {field}; '
                'available choices: {choices}'
                .format_map(locals()))
        return value

    def insert_locations(self, data):
        locations = []
        building_uses = {r.name: r for r in BuildingUse.objects.all()}
        watersheds = {r.name: r for r in Watershed.objects.all()}

        # Used to keep track of names already used so we can ensure each
        # location has a unique name and slug.
        names = set()

        for row in data:
            name = row['name'] or row['project']

            if name is None:
                self.print(
                    'Name (and project) not set for location: {row}; skipping'
                    .format_map(locals()))
                continue

            i = 1
            base_name = name
            while name in names:
                name = '{base_name}-{i}'.format_map(locals())
                i += 1

            names.add(name)

            building_use = self.choice(row, 'building_use', building_uses)
            watershed = self.choice(row, 'watershed', watersheds, null=True)

            coordinates = {'x': row['longitude'], 'y': row['latitude']}
            point = 'POINT({x} {y})'.format_map(coordinates)
            if coordinates['x'] is None or coordinates['y'] is None:
                self.print(
                    'Coordinates not set for location "{name}": {point}; skipping'
                    .format_map(locals()))
                continue

            location = Location(
                name=name,
                point=point,
                building_use=building_use,
                watershed=watershed,
            )
            location.set_neighborhood_automatically()
            locations.append(location)

        num_locations = len(locations)
        self.print('Creating', num_locations, 'locations...')
        if self.real_run:
            Location.objects.bulk_create(locations)

    def column_to_table(self, data, model, from_field_name=None, to_field_name='name'):
        """Take column values for field from data and insert into table.

        Args:
            data: A list of dicts
            model: A Django model class
            from_field_name: Field to extract values from (derived from ``model``
                if not specified)
            to_field_name: Model field name to set

        """
        model_name = model.__name__
        if from_field_name is None:
            from_field_name = camel_case_to_spaces(model_name).replace(' ', '_')

        self.print('Extracting', from_field_name, 'values...')
        values = {row[from_field_name] for row in data}
        values = {value for value in values if value is not None}
        values = {self.normalize_name(value) for value in values}
        num_values = len(values)
        self.print('Found', num_values, 'distinct, non-empty', from_field_name, 'values:')
        for value in sorted(values):
            self.print('    "{}"'.format(value))

        records = [model(**{to_field_name: value}) for value in values if value]
        num_records = len(records)
        self.print('Inserting', num_records, model_name, 'records...')
        if self.real_run:
            model.objects.bulk_create(records)
