""" ArcGIS python toolboxes for python-tidegates.

This contains Classes compatible with ArcGIS python toolbox
infrastructure.

(c) Geosyntec Consultants, 2015.

Released under the BSD 3-clause license (see LICENSE file for more info)

Written by Paul Hobson (phobson@geosyntec.com)

"""


import os
import sys
import glob
import datetime
from textwrap import dedent
from collections import OrderedDict

import arcpy
import numpy

import tidegates
from tidegates import utils


# ALL ELEVATIONS IN FEET
SEALEVELRISE = numpy.arange(7)
SURGES = OrderedDict(MHHW=4.0)
SURGES['10yr'] = 8.0
SURGES['50yr'] = 9.6
SURGES['100yr'] = 10.5


class StandardScenarios(object):
    """
    ArcGIS Python toolbox to analyze floods during the standard sea
    level rise and storm surge scenarios.

    Parameters
    ----------
    None

    See also
    --------
    Flooder

    """
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        # std attributes
        self.label = "2 - Evaluate all standard scenarios"
        self.canRunInBackground = True
        self.description = dedent("""
        Allows the user to recreate the standard scenarios with their
        own input.

        The standard scenarios are each combination of storm surges
        (MHHW, 10-yr, 50-yr, 100-yr) and sea level rise up to 6 feet in
        1-ft increments.
        """)

        # lazy properties
        self._workspace = None
        self._dem = None
        self._polygons = None
        self._ID_column = None
        self._flood_output = None
        self._building_output = None
        self._wetland_output = None
        self._wetlands = None
        self._buildings = None

    def isLicensed(self):
        """ PART OF THE ESRI BLACK BOX.

        Esri says:

            Set whether tool is licensed to execute.


        So I just make this always true b/c it's an open source project
        with a BSD license -- (c) Geosyntec Consultants -- so who cares?

        """
        return True

    def updateMessages(self, parameters): # pragma: no cover
        """ PART OF THE ESRI BLACK BOX.

        Esri says:

            Modify the messages created by internal validation for each
            parameter of the tool.  This method is called after internal
            validation.


        But I have no idea when or how internal validation is called so
        that's pretty useless information.

        """
        return

    def updateParameters(self, parameters): # pragma: no cover
        """ PART OF THE ESRI BLACK BOX.

        Automatically called when any parameter is updated in the GUI.

        Flow is like this:
            1. User interacts with GUI, filling out some input element
            2. self.getParameterInfo is called
            3. Parameteter are fed to this method as a list

        I used to set the parameter dependecies in here, but that didn't
        work. So now this does nothing and dependecies are set when the
        parameters (as class properties) are created (i.e., called for
        the first time).

        """
        return

    def getParameterInfo(self):
        """ PART OF THE ESRI BLACK BOX

        This *must* return a list of all of the parameter definitions.

        Esri recommends that you create all of the parameters in here,
        and always return that list. I instead chose to create the list
        from the class properties I've defined. Accessing things with
        meaningful names is always better, in my opinion.

        """
        return self._params_as_list()

    def execute(self, parameters, messages): # pragma: no cover
        """ PART OF THE ESRI BLACK BOX

        This method is called when the tool is actually executed. It
        gets passed magics lists of parameters and messages that no one
        can actually see.

        Due to this mysterious nature, I do the following:

        1) turn all of the elements of the list into a dictionary
           so that we can access them in a meaningful way. This
           means, instead of doing something like

        .. code-block:: python

           dem = parameters[0].valueAsText
           zones = parameters[1].valueAsText
           # yada yada
           nth_param = parameters[n].valueAsText

       for EVERY. SINGLE. PARAMETER, we can instead do something like:

        .. code-block:: python

           params = self._get_parameter_values(parameters, multivals=['elevation'])
           dem = params['dem']
           zones = params['zones'].
           # yada

       This is much cleaner, in my opinion, and we don't have to
       magically know where in the list of parameters e.g., the
       DEM is found. Take note, Esri.

        2) generate a list of scenarios usings `self._make_scenarios`.
        3) loop through those scenarios.
        4) call ``self.analyze`` on each scenario.
        5) call ``self.finish_results`` on all of the layers
           generated by the loop.

        """

        params = self._get_parameter_values(parameters, multivals=['elevation'])
        self.main_execute(**params)

        return None

    @staticmethod
    def _set_parameter_dependency(downstream, *upstream):
        """ Set the dependecy of a arcpy.Parameter

        Parameters
        ----------
        downstream : arcpy.Parameter
            The Parameter that is reliant on an upstream parameter.
        upstream : acrpy.Parameters
            An arbitraty number of "upstream" parameters on which the
            "downstream" parameter depends.

        Returns
        -------
        None

        See Also
        --------
        http://goo.gl/HcR6WJ

        """

        downstream.parameterDependencies = [u.name for u in upstream]

    @staticmethod
    def _show_header(title, verbose=True):
        """ Creates and shows a little header from a title.

        Parameters
        ----------
        title : str
            The message to be shown
        verbose : bool, optional (True)
            Whether or not the final message should be printed

        Returns
        -------
        header : str
            The formatted title as a header

        Examples
        --------
        >>> Flooder._show_header('Hello, world', verbose=True)
            'Hello, world'
             --------------

        """
        underline = ''.join(['-'] * len(title))
        header = '\n{}\n{}'.format(title, underline)
        utils._status(header, verbose=verbose, asMessage=True, addTab=False)
        return header

    @staticmethod
    def _add_to_map(layerfile, mxd=None):
        """ Adds a layer or raster to the "CURRENT" map.

        Parameters
        ----------
        layerfile : str
            Path to the layer or raster that will be added
        mxd : str, optional
            Path to an ESRI mapdocument.

        Returns
        -------
        ezmd : EasyMapDoc
            The "easy map document" to which ``layerfile`` was added.

        """
        if mxd is None:
            mxd = 'CURRENT'
        ezmd = utils.EasyMapDoc(mxd)
        if ezmd.mapdoc is not None:
            ezmd.add_layer(layerfile)

        return ezmd

    @staticmethod
    def _add_scenario_columns(layer, elev=None, surge=None, slr=None):
        """ Adds scenario information to a shapefile/layer

        Parameters
        ----------
        layer : str or arcpy.mapping.Layer
            The path to the layer, or the actual layer object that
            will be modified in-place.
        elev, slr : float, optional
            Final elevation and sea level rise associated with the
            scenario.
        surge : str, optional
            The name of the storm surge associated with the scenario
            (e.g., MHHW, 100yr).

        Returns
        -------
        None

        """


        if elev is not None:
            utils.add_field_with_value(
                table=layer,
                field_name="flood_elev",
                field_value=float(elev),
                msg="Adding 'flood_elev' field to ouput",
                verbose=True,
                asMessage=True
            )

        if surge is not None:
            utils.add_field_with_value(
                table=layer,
                field_name="surge",
                field_value=str(surge),
                field_length=10,
                msg="Adding storm surge field to ouput",
                verbose=True,
                asMessage=True
            )

        if slr is not None:
            utils.add_field_with_value(
                table=layer,
                field_name="slr",
                field_value=int(slr),
                msg="Adding sea level rise field to ouput",
                verbose=True,
                asMessage=True
            )

    @staticmethod
    def _get_parameter_values(parameters, multivals=None):
        """ Returns a dictionary of the parameters values as passed in from
        the ESRI black box. Keys are the parameter names, values are the
        actual values (as text) of the parameters.

        Parameters
        ----------
        parameters : list of arcpy.Parameter-type thingies
            The list of whatever-the-hell ESRI passes to the ``execute``
            method of a toolbox.
        multivals : str or list of str, optional
            Parameter names that can take mulitiple values.

        Returns
        -------
        params : dict
            A python dictionary of parameter values mapped to the
            parameter names.

        """

        if multivals is None:
            multivals = []
        elif numpy.isscalar(multivals):
            multivals = [multivals]

        params = {}
        for p in parameters:
            value = p.valueAsText
            if p.name in multivals:
                value = value.split(';')
            params[p.name] = value

        return params

    @staticmethod
    def _prep_flooder_input(elev=None, surge=None, slr=None, flood_output=None):
        """ Prepares the basic inputs to the `_do_flood` method.

        Parameters
        ----------
        elev, slr : float, optional
            Final elevation and sea level rise associated with the
            scenario.
        surge : str, optional
            The name of the storm surge associated with the scenario
            (e.g., MHHW, 100yr).
        flood_output : str
            Path/filename to where the final flooded areas will be
            saved.

        Returns
        -------
        elevation : float
            Flood elevation for this scenario.
        title : str
            The basis of the header to be displayed as an arcpy.Message.
        temp_fname : str
            Path/name of the temporary file where the intermediate
            output will be saved.

        """
        if elev is None:
            elevation = float(slr + SURGES[surge])
            title = "Analyzing flood elevation: {} ft ({}, {})".format(elevation, surge, slr)
        else:
            elevation = float(elev)
            title = "Analyzing flood elevation: {} ft".format(elevation)

        if flood_output is None:
            raise ValueError('must provide a `flood_output`')

        basename, ext = os.path.splitext(flood_output)
        temp_fname = basename + str(elevation).replace('.', '_') + ext

        return elevation, title, temp_fname

    @property
    def workspace(self):
        """ The directory or geodatabase in which the analysis will
        occur.

        """

        if self._workspace is None:
            self._workspace = arcpy.Parameter(
                displayName="Analysis WorkSpace",
                name='workspace',
                datatype="DEWorkspace",
                parameterType="Required",
                direction="Input",
                multiValue=False
            )
        return self._workspace

    @property
    def dem(self):
        """ DEM file (topography) to be used in the analysis.

        """
        if self._dem is None:
            self._dem = arcpy.Parameter(
                displayName="Digital Elevation Model",
                name="dem",
                datatype="DERasterDataset",
                parameterType="Required",
                direction="Input",
                multiValue=False
            )
            self._set_parameter_dependency(self._dem, self.workspace)
        return self._dem

    @property
    def polygons(self):
        """ The Zones of influence polygons to be used in the analysis.

        """

        if self._polygons is None:
            self._polygons = arcpy.Parameter(
                displayName="Tidegate Zones of Influence",
                name="polygons",
                datatype="DEFeatureClass",
                parameterType="Required",
                direction="Input",
                multiValue=False
            )
            self._set_parameter_dependency(self._polygons, self.workspace)
        return self._polygons

    @property
    def ID_column(self):
        """ Name of the field in `polygons` that uniquely identifies
        each zone of influence.

        """

        if self._ID_column is None:
            self._ID_column = arcpy.Parameter(
                displayName="Column with Tidegate IDs",
                name="ID_column",
                datatype="Field",
                parameterType="Required",
                direction="Input",
                multiValue=False
            )
            self._set_parameter_dependency(self._ID_column, self.polygons)
        return self._ID_column

    @property
    def flood_output(self):
        """ Where the flooded areas for each scenario will be saved.

        """

        if self._flood_output is None:
            self._flood_output = arcpy.Parameter(
                displayName="Output floods layer/filename",
                name="flood_output",
                datatype="GPString",
                parameterType="Required",
                direction="Input"
            )
        return self._flood_output

    @property
    def building_output(self):
        """ Where the flooded buildings for each scenario will be saved.

        """

        if self._building_output is None:
            self._building_output = arcpy.Parameter(
                displayName="Output layer/filename of impacted buildings",
                name="building_output",
                datatype="GPString",
                parameterType="Optional",
                direction="Input"
            )
        return self._building_output

    @property
    def wetland_output(self):
        """ Where the flooded wetlands for each scenario will be saved.

        """

        if self._wetland_output is None:
            self._wetland_output = arcpy.Parameter(
                displayName="Output layer/filename of impacted wetlands",
                name="wetland_output",
                datatype="GPString",
                parameterType="Optional",
                direction="Input"
            )
        return self._wetland_output

    @property
    def wetlands(self):
        """ Input layer of wetlands.

        """

        if self._wetlands is None:
            self._wetlands = arcpy.Parameter(
                displayName="Wetlands",
                name="wetlands",
                datatype="DEFeatureClass",
                parameterType="Optional",
                direction="Input",
                multiValue=False
            )
            self._set_parameter_dependency(self._wetlands, self.workspace)
        return self._wetlands

    @property
    def buildings(self):
        """ Input layer of building footprints.

        """

        if self._buildings is None:
            self._buildings = arcpy.Parameter(
                displayName="Buildings footprints",
                name="buildings",
                datatype="DEFeatureClass",
                parameterType="Optional",
                direction="Input",
                multiValue=False
            )
            self._set_parameter_dependency(self._buildings, self.workspace)
        return self._buildings

    def _params_as_list(self):
        params = [
            self.workspace,
            self.dem,
            self.polygons,
            self.ID_column,
            self.flood_output,
            self.wetlands,
            self.wetland_output,
            self.buildings,
            self.building_output,
        ]
        return params

    def _make_scenarios(self, **params):
        """ Makes a list of dictionaries of all scenario parameters that
        will be analyzed by the toolbox.

        Parameters
        ----------
        **params : keyword arguments
            Keyword arguments of analysis parameters generated by
            `self._get_parameter_values`

        Returns
        -------
        scenarios : list of dictionaries
            A list of dictionaries describing each scenario to be
            analyzed. Keys of the dictionaries will be:
              - elev -- the custom elevation
              - surge_name - the name of a storm surge event
              - surge_elev - the elevation associated with "surge_name"
              - slr - the amount of sea level rise to be considered.

            When analyzing custom elevations, all other entries are set
            to None. Likewise, when evaluating standard scenarios,
            "elev" is None.

        """
        scenario_list = []

        # if elevation is in the parameters, then we *know* this is
        # a custom flood elevation. Otherwise, we're evaluating the
        # standard scenarios.
        elevations = params.get('elevation', None)
        if numpy.isscalar(elevations):
            elevations = [elevations]

        # standard scenarios
        if elevations is None:
            for surge_name, surge_elev in SURGES.items():
                for slr in SEALEVELRISE:
                    scenario = {
                        'elev': None,
                        'surge_name': surge_name,
                        'surge_elev': surge_elev,
                        'slr': slr
                    }
                    scenario_list.append(scenario)
        # custom floods
        else:
            for elev in elevations:
                scenario = {
                    'elev': float(elev),
                    'surge_name': None,
                    'surge_elev': None,
                    'slr': None
                }
                scenario_list.append(scenario)

        return scenario_list

    def analyze(self, elev=None, surge=None, slr=None, **params):
        """ Tool-agnostic helper function for ``main_execute``.

        Parameters
        ----------
        elev : float, optional
            Custom elevation to be analyzed
        slr : float, optional
            Sea level rise associated with the standard scenario.
        surge : str, optional
            The name of the storm surge associated with the scenario
            (e.g., MHHW, 100yr).
        **params : keyword arguments
            Keyword arguments of analysis parameters generated by
            `self._get_parameter_values`

        Returns
        -------
        floods, flooded_wetlands, flooded_buildings : arcpy.mapping.Layers
            Layers (or None) of the floods and flood-impacted wetlands
            and buildings, respectively.

        """

        # prep input
        elev, title, floods_path = self._prep_flooder_input(
            flood_output=params['flood_output'],
            elev=elev,
            surge=surge,
            slr=slr,
        )

        # define the scenario in the message windows
        self._show_header(title)

        # run the scenario and add its info the output attribute table
        flooded_polygons = tidegates.flood_area(
            dem=params['dem'],
            polygons=params['polygons'],
            ID_column=params['ID_column'],
            elevation_feet=elev,
            filename=floods_path,
            verbose=True,
            asMessage=True
        )
        self._add_scenario_columns(flooded_polygons.dataSource, elev=elev, surge=surge, slr=slr)

        # setup temporary files for impacted wetlands and buildings
        wl_path = utils.create_temp_filename(floods_path, prefix="_wetlands_")
        bldg_path = utils.create_temp_filename(floods_path, prefix="_buildings_")

        # asses impacts due to flooding
        fldlyr, wtlndlyr, blgdlyr = tidegates.assess_impact(
            floods_path=floods_path,
            ID_column=params['ID_column'],
            wetlands_path=params.get('wetlands', None),
            wetlands_output=wl_path,
            buildings_path=params.get('buildings', None),
            buildings_output=bldg_path,
            cleanup=False,
            verbose=True,
            asMessage=True,
        )

        if wtlndlyr is not None:
            self._add_scenario_columns(wtlndlyr.dataSource, elev=elev, surge=surge, slr=slr)

        return fldlyr, wtlndlyr, blgdlyr

    @staticmethod
    @utils.update_status()
    def finish_results(outputname, results, **kwargs):
        """ Merges and cleans up compiled output from `analyze`.

        Parameters
        ----------
        outputname : str
            Path to where the final file sould be saved.
        *results : list of str
            Lists of all of the floods, flooded wetlands, and flooded
            buildings, respectively, that will be merged and deleted.
        sourcename : str, optional
            Path to the original source file of the results. If
            provided, its attbutes will be spatially joined to the
            concatenated results.

        Returns
        -------
        None

        """

        sourcename = kwargs.pop('sourcename', None)
        cleanup = kwargs.pop('cleanup', True)

        if outputname is not None:
            if sourcename is not None:
                tmp_fname = utils.create_temp_filename(outputname)
                utils.concat_results(tmp_fname, *results)
                utils.join_results_to_baseline(
                    outputname,
                    utils.load_data(tmp_fname, "layer"),
                    utils.load_data(sourcename, 'layer')
                )
                utils.cleanup_temp_results(tmp_fname)

            else:
                utils.concat_results(outputname, *results)

        if cleanup:
            utils.cleanup_temp_results(*results)

    def main_execute(self, **params):
        """ Performs the flood-impact analysis on multiple flood
        elevations.

        Parameters
        ----------
        workspace : str
            The folder or geodatabase where the analysis will be
            executed.
        polygons : str
            Name of zones of influence layer.
        ID_column : str
            Name of the field in ``polygons`` that uniquely identifies
            each zone of influence.
        wetlands, buildings : str
            Names of the wetland and building footprint layers.
        flood_output, wetland_output, building_output : str
            Filenames where the output will be saved.
        dem : str
            Filename of the digital elevation model (topography data)
            to be used in determinging the inundated areas.
        elevation : list, optional
            List of (custom) flood elevations to be analyzed. If this is
            not provided, *all* of the standard scenarios will be
            evaluated.

        Returns
        -------
        None

        """

        wetlands = params.get('wetlands', None)
        buildings = params.get('buildings', None)

        all_floods = []
        all_wetlands = []
        all_buildings = []

        with utils.WorkSpace(params['workspace']), utils.OverwriteState(True):
            for scenario in self._make_scenarios(**params):
                fldlyr, wtlndlyr, blgdlyr = self.analyze(
                    elev=scenario['elev'],
                    surge=scenario['surge_name'],
                    slr=scenario['slr'],
                    **params
                )
                all_floods.append(fldlyr.dataSource)
                if wetlands is not None:
                    all_wetlands.append(wtlndlyr.dataSource)

                if buildings is not None:
                    all_buildings.append(blgdlyr.dataSource)

            self.finish_results(
                params['flood_output'],
                all_floods,
                msg="Merging and cleaning up all flood results",
                verbose=True,
                asMessage=True,
            )

            if wetlands is not None:
                wtld_output = params.get(
                    'wetland_output',
                    utils.create_temp_filename(params['wetlands'], prefix='output_')
                )
                self.finish_results(
                    wtld_output,
                    all_wetlands,
                    sourcename=params['wetlands'],
                    msg="Merging and cleaning up all wetlands results",
                    verbose=True,
                    asMessage=True,
                )

            if buildings is not None:
                bldg_output = params.get(
                    'building_output',
                    utils.create_temp_filename(params['buildings'], prefix='output_')
                )
                self.finish_results(
                    bldg_output,
                    all_buildings,
                    sourcename=params['buildings'],
                    msg="Merging and cleaning up all buildings results",
                    verbose=True,
                    asMessage=True,
                )


class Flooder(StandardScenarios):
    """
    ArcGIS Python toolbox to analyze custom flood elevations.

    Parameters
    ----------
    None

    See also
    --------
    StandardScenarios

    """

    def __init__(self):
        # std attributes
        super(Flooder, self).__init__()
        self.label = "1 - Create Flood Scenarios"
        self.description = dedent("""
        Allows the user to create a custom flooding scenario given the
        following:
            - A DEM of the coastal area
            - A polygon layer describing the zones of influence of each
              tidegate
        """)

        # lazy properties
        self._elevation = None

    def _params_as_list(self):
        params = [
            self.workspace,
            self.dem,
            self.polygons,
            self.ID_column,
            self.elevation,
            self.flood_output,
            self.wetlands,
            self.wetland_output,
            self.buildings,
            self.building_output,
        ]
        return params

    @property
    def elevation(self):
        """ The flood elevation for a custom scenario.

        """

        if self._elevation is None:
            self._elevation = arcpy.Parameter(
                displayName="Water Surface Elevation",
                name="elevation",
                datatype="GPDouble",
                parameterType="Required",
                direction="Input",
                multiValue=True
            )
        return self._elevation
