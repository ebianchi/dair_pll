"""Script to help generate plots for CoRL 2023 submission.

First, this script compiles all results into a json file.  Then, this script can
gather the results from the json file and generate plots from them.

The json file has the following format:
{
    experiment_1: {
        system:  cube/elbow
        prefix:  e.g. sc for 'cube' experiments
        gravity_sweep: {
            gravity_frac_1: {
                run_1: {
                    structured:  bool
                    contactnets:  bool
                    loss_variation:  int
                    residual:  bool
                    g_frac:  float
                    result_set:  test/validation
                    results: {
                        metric_1:  float
                        metric_2:  float
                        ...
                    }
                    learned_params: {
                        body_1: {
                            param_1:  float
                            param_2:  float
                            ...
                        }
                        body_2: {...}
                    }
                    target_trajs: []      <-- excluded from json due to datatype
                    prediction_trajs: []  <-- excluded from json due to datatype
                }
                run_2: {...}
                run_3: {...}
                ...
            }
            gravity_frac_2: {...}
            gravity_frac_3: {...}
            ...
        }
    }
    experiment_2: {...}
    experiment_3: {...}
    ...
}
...where `experiment_1` might be 'cube', corresponding to the real data sweep
results.
"""

import json
import os
import os.path as op
import pdb
import pickle
import torch
from copy import deepcopy

import numpy as np

from dair_pll.deep_learnable_system import DeepLearnableSystemConfig
from dair_pll.drake_experiment import MultibodyLosses
from dair_pll.geometry import _NOMINAL_HALF_LENGTH
from dair_pll.inertia import InertialParameterConverter


"""Note:  might need the below in drake_experiment.py for backwards
compatibility:

@dataclass
class DrakeMultibodyLearnableExperimentConfig(SupervisedLearningExperimentConfig
                                             ):
    visualize_learned_geometry: bool = True
    \"""Whether to use learned geometry in trajectory overlay visualization.\"""
"""


# Directory management.
RESULTS_DIR = op.join(op.dirname(__file__), '..', 'results')
OUTPUT_DIR = op.join(op.dirname(__file__), '..', 'plots')
JSON_OUTPUT_FILE = op.join(op.dirname(__file__), 'gravity_results.json')

BODY_NAMES_BY_SYSTEM = {'cube': ['body'], 'elbow': ['elbow_1', 'elbow_2'],
                        'asymmetric': ['body']}
BODY_PARAMETERS = {
    'm': 'Mass',
    'com_x': 'CoM x',
    'com_y': 'CoM y',
    'com_z': 'CoM z',
    'I_xx': 'I_xx',
    'I_yy': 'I_yy',
    'I_zz': 'I_zz',
    'I_xy': 'I_xy',
    'I_xz': 'I_xz',
    'I_yz': 'I_yz',
    'mu': 'Friction coefficient',
    'center_x': 'Geometry center x',
    'center_y': 'Geometry center y',
    'center_z': 'Geometry center z',
    'diameter_x': 'Geometry diameter x',
    'diameter_y': 'Geometry diameter x',
    'diameter_z': 'Geometry diameter x'}
POLYGON_GEOMETRY_PARAMETERS = ['center_x', 'center_y', 'center_z',
                               'diameter_x', 'diameter_y', 'diameter_z']

INERTIA_KEY = 'multibody_terms.lagrangian_terms.inertial_parameters'
FRICTION_KEY = 'multibody_terms.contact_terms.friction_params'
GEOMETRY_PREFIX = 'multibody_terms.contact_terms.geometries'
GEOMETRY_KEY_BODY_1 = f'{GEOMETRY_PREFIX}.2.vertices_parameter'
GEOMETRY_KEY_BODY_2 = f'{GEOMETRY_PREFIX}.0.vertices_parameter'
# GEOMETRY_KEY2 = 'multibody_terms.contact_terms.geometries.0.length_params'

FRICTION_INDEX_BY_BODY_NAME = {'body': 0, 'elbow_2': 0, 'elbow_1': 2}

PERFORMANCE_METRICS = ['delta_v_squared_mean',    'v_plus_squared_mean',
                    'model_loss_mean',            'oracle_loss_mean',
                    'model_trajectory_mse_mean',  'oracle_trajectory_mse_mean',
                    'model_pos_int_traj',         'oracle_pos_int_traj',
                    'model_angle_int_traj',       'oracle_angle_int_traj',
                    'model_penetration_int_traj', 'oracle_penetration_int_traj']

GRAVITY_FRACTIONS = {0: 0., 1: 0.5, 2: 1., 3: 1.5, 4: 2.}
SYSTEMS = ['cube', 'elbow', 'asymmetric']
ORDERED_INERTIA_PARAMS = ['m', 'px', 'py', 'pz', 'I_xx', 'I_yy', 'I_zz',
                          'I_xy', 'I_xz', 'I_yz']
TARGET_SAMPLE_KEY = 'model_target_sample'
PREDICTION_SAMPLE_KEY = 'model_prediction_sample'


# Template dictionaries, from low- to high-level.
RUN_DICT = {'structured': None, 'contactnets': None, 'loss_variation': None,
            'residual': None, 'result_set': None, 'results': None,
            'learned_params': None}
EXPERIMENT_DICT = {'system': None, 'prefix': None,
                   'gravity_sweep': None}

BAD_RUN_NUMBERS = [0, 1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 15, 16, 17, 18, 19, 21, 22]

# Prepend the below with 'gravity_sweep_' and postpend with '-#' to get the
# folders.
EXPERIMENTS = {#'cube': {'system': 'cube', 'prefix': 'gc'},
               'elbow': {'system': 'elbow', 'prefix': 'ge'}}

g_index_to_use = 0


# ============================= Helper functions ============================= #
# Return an empty data sweep dictionary, to prevent unintended data retention.
def make_empty_gravity_sweep_dict():
    new_dict = {}
    for grav_i in GRAVITY_FRACTIONS.keys():
        new_dict.update({GRAVITY_FRACTIONS[grav_i]: {}})
    return new_dict


# Extract information out of a configuration object.
def get_run_info_from_config(config):
    run_dict = deepcopy(RUN_DICT)

    run_dict['structured'] = False if \
        isinstance(config.learnable_config, DeepLearnableSystemConfig) else True

    if run_dict['structured']:
        run_dict['contactnets'] = True if \
            config.learnable_config.loss==MultibodyLosses.CONTACTNETS_LOSS \
            else False
        run_dict['loss_variation'] = config.learnable_config.loss_variation
        run_dict['residual'] = config.learnable_config.do_residual
        run_dict['g_frac'] = config.learnable_config.g_frac
        run_dict['result_set'] = 'test'

    else:
        # Can randomly (but evenly) assign gravity fraction to end-to-end
        # experiments since the g_frac doesn't affect the experiment.
        global g_index_to_use
        run_dict['g_frac'] = GRAVITY_FRACTIONS[g_index_to_use]
        g_index_to_use = (g_index_to_use+1) % 5

    run_dict['result_set'] = 'test'
    run_name = config.run_name

    return run_name, run_dict


# Calculate geometry measurements from a set of polygon vertices.
def get_geometry_metrics_from_params(geom_params):
    # First, convert the parameters to meters.
    vertices = geom_params * _NOMINAL_HALF_LENGTH

    # Extract diameters and centers.
    mins = vertices.min(axis=0).values
    maxs = vertices.max(axis=0).values

    diameters = maxs - mins
    centers = (maxs + mins)/2

    geom_dict = {'diameter_x': diameters[0].item(),
                 'diameter_y': diameters[1].item(),
                 'diameter_z': diameters[2].item(),
                 'center_x': centers[0].item(),
                 'center_y': centers[1].item(),
                 'center_z': centers[2].item(),
                 'vertices': vertices.tolist()}
    return geom_dict

def geometry_keys_by_sys_and_bodies(system, body_name):
    if system == 'cube' or system == 'asymmetric':
        return {'body': GEOMETRY_KEY_BODY_2}
    return {'elbow_1': GEOMETRY_KEY_BODY_1, 'elbow_2': GEOMETRY_KEY_BODY_2}


# Get individual physical parameters from best learned system state.
def get_physical_parameters(system, body_names, best_system_state):
    physical_params_dict = {}

    theta = best_system_state[INERTIA_KEY]
    friction_params = best_system_state[FRICTION_KEY]
    if GEOMETRY_KEY_BODY_2 in best_system_state.keys():
        geometry_keys = geometry_keys_by_sys_and_bodies(system, body_names)
    else:
        geometry_keys = {}
        print(f'\t\tFound non-polygon; won\'t gather geometry results.')

    inertia_pi_cm_params = InertialParameterConverter.theta_to_pi_cm(theta)

    # Loop over each body.
    for i in range(len(body_names)):
        body = body_names[i]

        # First, get the inertial parameters.
        i_params = inertia_pi_cm_params[i, :]
        i_params[1:4] /= i_params[0].item()  # Divide out the mass.

        body_params = {}

        for j in range(10):
            body_params.update({ORDERED_INERTIA_PARAMS[j]: i_params[j].item()})

        # Second, get the friction parameters.
        mu_index = FRICTION_INDEX_BY_BODY_NAME[body]
        body_params.update({'mu': friction_params[mu_index].item()})

        # Third, get the geometry parameters.
        try:
            geometry_params = best_system_state[geometry_keys[body]]
            geom_dict = get_geometry_metrics_from_params(geometry_params)
            body_params.update(geom_dict)
        except:
            pass

        # Store the results.
        physical_params_dict.update({body: body_params})

    return physical_params_dict


# Extract the desired statistics from the larger stats file.  Will convert
# numpy arrays into averages.
def get_performance_from_stats(stats, set_name):
    performance_dict = {}
    for metric in PERFORMANCE_METRICS:
        key = f'{set_name}_{metric}'
        try:
            if type(stats[key]) == np.ndarray:
                performance_dict.update({key: np.average(stats[key])})
            else:
                performance_dict.update({key: stats[key]})
        except:
            print(f'\t\tDidn\'t find {key} in stats...')
    return performance_dict


# Extract the target and prediction trajectories from the larger stats file.
# This isn't called since the datatype isn't json serializable, but keeping this
# function here for future reference.
def get_sample_trajectories_from_stats(stats, set_name):
    targets, predictions = [], []

    target_key = f'{set_name}_{TARGET_SAMPLE_KEY}'
    try:
        targets = stats[target_key]
    except:
        print(f'\t\tDidn\'t find {target_key} in stats...')

    prediction_key = f'{set_name}_{PREDICTION_SAMPLE_KEY}'
    try:
        predictions = stats[prediction_key]
    except:
        print(f'\t\tDidn\'t find {prediction_key} in stats...')

    return targets, predictions


# Get run configuration, statistics, and checkpoint objects.  Returns None for
# any that don't exist.
def get_config_stats_checkpoint(runs_path, run):
    config, stats, checkpoint = None, None, None

    config_file = op.join(runs_path, run, 'config.pkl')
    if op.exists(config_file):
        with open(config_file, 'rb') as file:
            config = pickle.load(file)

    stats_file = op.join(runs_path, run, 'statistics.pkl')
    if op.exists(stats_file):
        with open(stats_file, 'rb') as file:
            stats = pickle.load(file)

    checkpoint_file = op.join(runs_path, run, 'checkpoint.pt')
    if op.exists(checkpoint_file):
        checkpoint = torch.load(checkpoint_file)

    return config, stats, checkpoint


# =============================== Gather data ================================ #
# Loop over dataset categories, then dataset size, then individual runs.
runs_needing_statistics = []
results = {}

sent_warning = False

for experiment in EXPERIMENTS.keys():
    print(f'\n\n============== Starting {experiment} ==============')
    exp_dict = deepcopy(EXPERIMENT_DICT)
    system = EXPERIMENTS[experiment]['system']
    exp_dict['system'] = system
    exp_dict['prefix'] = EXPERIMENTS[experiment]['prefix']
    exp_dict['gravity_sweep'] = make_empty_gravity_sweep_dict()

    body_names = BODY_NAMES_BY_SYSTEM[system]

    results_folder_name = f'gravity_sweep_{experiment}'
    runs_path = op.join(RESULTS_DIR, results_folder_name, 'runs')
    if not op.isdir(runs_path):
        print(f'Could not find {results_folder_name} runs; skipping.')
        continue
        
    print(f'\nFound {results_folder_name}.')

    for run in os.listdir(runs_path):
        if int(run[2:4]) in BAD_RUN_NUMBERS:
            continue
            if not sent_warning:
                print(f'WARNING: Skipping run numbers {BAD_RUN_NUMBERS}')
                sent_warning = True

        config, stats, checkpoint = \
            get_config_stats_checkpoint(runs_path, run)

        if stats == None:
            print(f'\tNo stats file for {run}; skipping.')
            runs_needing_statistics.append(
                op.join(runs_path, run).split('results/')[-1])
            continue

        assert config != None and checkpoint != None
        print(f'\tFound statistics for {run}.')

        run_key, run_dict = get_run_info_from_config(config)

        performance_dict = \
            get_performance_from_stats(stats, run_dict['result_set'])
        run_dict['results'] = performance_dict

        if run_dict['structured']:
            best_system_state = checkpoint['best_learned_system_state']
            params_dict = get_physical_parameters(system, body_names,
                                                  best_system_state)
            run_dict['learned_params'] = params_dict

        grav_frac = run_dict['g_frac']
        exp_dict['gravity_sweep'][grav_frac].update({run_key: run_dict})

    results.update({experiment: exp_dict})

print(f'\n\nSaving results to json file.')
with open(JSON_OUTPUT_FILE, 'w') as file:
    json.dump(results, file, indent=2)

pdb.set_trace()

print(f'\n\nRuns needing statistics: {runs_needing_statistics}')
