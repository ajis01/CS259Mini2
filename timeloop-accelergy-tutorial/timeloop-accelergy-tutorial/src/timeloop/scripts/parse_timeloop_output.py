#! /usr/bin/env python3

# Copyright (c) 2019, NVIDIA CORPORATION. All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#  * Neither the name of NVIDIA CORPORATION nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
# OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import argparse
import numpy as np
import os
import pickle
import pprint
import xml.etree.ElementTree as ET

# Output file names.
out_prefix = "timeloop-mapper."
xml_file_name = out_prefix + "map+stats.xml";

def get_stat(stats, stat, cast):
    items = stats.findall(stat)[0].findall('PerDataSpace')[0].findall('item')
    count = len(items)
    out = np.array([0]*count, dtype=cast)
    for j in range(count):
        if stat == 'ingresses':
            value = sum([cast(i.text) for i in items[j].findall('item')])       
        else:
            value = cast(items[j].text)
        out[j] = value
    return out 

def parse_timeloop_stats(filename):
    if (os.path.isdir(filename)):
        filename = os.path.join(filename, xml_file_name)
    tree = ET.parse(filename)
    root = tree.getroot()
    
    # Parse out the problem shape
    problem_dims = root.findall('a')[0].findall('workload_')[0].findall('bounds_')[0].findall('item')
    problem = {'FH': int(problem_dims[0].findall('second')[0].text),\
               'FW': int(problem_dims[1].findall('second')[0].text),\
               'OH': int(problem_dims[2].findall('second')[0].text),\
               'OW': int(problem_dims[3].findall('second')[0].text),\
               'IC': int(problem_dims[4].findall('second')[0].text),\
               'OC': int(problem_dims[5].findall('second')[0].text),\
               'IN': int(problem_dims[6].findall('second')[0].text),\
              }

    macs = problem['FH']*problem['FW']*problem['IC']*problem['OH']*problem['OW']*problem['IN']*problem['OC']

    topology = root.findall('best_mapped_engine')[0].findall('topology_')[0]
    
    # Get the list of storage elements
    storage_levels = topology.findall('levels_')[0]
    num_storage_levels = int(storage_levels.findall('count')[0].text)    
    level_ptrs = storage_levels.findall('item')  
    
    # Initialize a dictionary that stores energy breakdown and other statistics
    energy_breakdown_pJ = {}

    arithmetic_level_found = False
    for level_ptr in level_ptrs:

        level = level_ptr.findall('px')[0]

        # The XML structure is interesting. Every Level gets a <px>, but
        # only the first object of each type gets a full class_id descriptor.
        # For example, the first model::BufferLevel item will get:
        #    <px class_id="9" class_name="model::BufferLevel" tracking_level="1" version="0" object_id="_1">
        # but subsequent levels will get something like: 
	#     <px class_id_reference="9" object_id="_2">
        # with increasing object_ids. We can keep a table of new class_ids as
        # we encounter them, but for now we'll just hack something that works.
        
        # Is this the Arithmetic level (the only one)?
        if 'class_id' in level.attrib and level.attrib['class_name'] == "model::ArithmeticUnits":
            assert arithmetic_level_found == False
            arithmetic_level_found = True
            cycles = int(level.findall('cycles_')[0].text)       
            utilized_instances = float(level.findall('utilized_instances_')[0].text)       
            total_instances_list = level.findall('specs_')[0].findall('instances')[0].findall('t_')
            if total_instances_list == []: # this happens when no mapping is returned by timeloop
                total_instances = 1 # dummy value
            else:
                total_instances = float(level.findall('specs_')[0].findall('instances')[0].findall('t_')[0].text)    
            arithmetic_utilization = utilized_instances/total_instances
            energy_breakdown_pJ['MAC'] = {'energy': float(level.findall('energy_')[0].text), 'utilization': arithmetic_utilization}       
            continue
            
        # Continue storage level stat extraction...
            
        # Level specifications
        specs = level.findall('specs_')[0]
        generic_level_specs = specs.findall('LevelSpecs')[0]
        level_name = generic_level_specs.findall('level_name')[0].text
        
        total_instances = int(specs.findall('instances')[0].findall('shared')[0].findall('t_')[0].text)
        total_capacity = int(specs.findall('size')[0].findall('shared')[0].findall('t_')[0].text)

        stats = level.findall('stats_')[0]
        
        # Storage access energy
        reads_per_instance = get_stat(stats, 'reads', int)   
        updates_per_instance = get_stat(stats, 'updates', int)   
        fills_per_instance = get_stat(stats, 'fills', int)   
        accesses_per_instance = reads_per_instance + updates_per_instance + fills_per_instance
        
        utilized_capacity = get_stat(stats, 'utilized_capacity', int)
        instances = get_stat(stats, 'utilized_instances', int) 
        clusters = get_stat(stats, 'utilized_clusters', int)   

        energy_per_access_per_instance = get_stat(stats, 'energy_per_access', float) 
        storage_access_energy_in_pJ = energy_per_access_per_instance * accesses_per_instance * instances
        read_energy = energy_per_access_per_instance * reads_per_instance * instances
        
        # Network energy
        network = stats.findall('network')[0]
        num_hops = get_stat(network, 'num_hops', float)
        energy_per_hop_per_instance = get_stat(network, 'energy_per_hop', float)
        ingresses = get_stat(network, 'ingresses', int)      
        network_energy_in_pJ = num_hops * ingresses * energy_per_hop_per_instance * instances
        
        # Add energy
        spatial_add_energy_per_instance = get_stat(network, 'spatial_reduction_energy', float) 
        temporal_add_energy_per_instance = get_stat(stats, 'temporal_reduction_energy', float) 
        temporal_add_energy = np.nansum(temporal_add_energy_per_instance * instances)
        spatial_add_energy = np.nansum(spatial_add_energy_per_instance * instances)

        # Address generation energy
        address_generation_energy_per_cluster = get_stat(stats, 'addr_gen_energy', float)
        address_generation_energy = np.nansum(address_generation_energy_per_cluster * clusters)

        # Special Case when the memory level is a dummy (capacity = 0)
        if total_capacity == 0:
            utilization = 0
        else:
            utilization = sum((utilized_capacity*instances)/(total_capacity*total_instances))

        energy_breakdown_pJ[level_name] = {\
            'energy': np.nansum(storage_access_energy_in_pJ) + np.nansum(network_energy_in_pJ) + temporal_add_energy + spatial_add_energy + address_generation_energy,\
            'storage_access_energy': np.nansum(storage_access_energy_in_pJ),\
            'read_energy': np.nansum(read_energy),\
            'temporal_add_energy': temporal_add_energy,\
            'spatial_add_energy': spatial_add_energy,\
            'address_generation_energy': address_generation_energy,\
            'network_energy': np.nansum(network_energy_in_pJ),\
            'energy_per_access_per_instance': energy_per_access_per_instance,\
            'reads_per_instance': reads_per_instance,\
            'updates_per_instance': updates_per_instance,\
            'fills_per_instance': fills_per_instance,\
            'accesses_per_instance': accesses_per_instance,\
            'instances': instances,\
            'utilization': utilization,\
            'num_hops': num_hops,\
            'ingresses': ingresses,\
            'energy_per_hop_per_instance': energy_per_hop_per_instance}
 
    energy_pJ =  sum([value['energy'] for key, value in energy_breakdown_pJ.items()])

    # Crude check to find out if timeloop produced an output.
    if arithmetic_level_found:
        output = {
            'problem': problem,
            'utilization': arithmetic_utilization,
            'cycles': cycles,
            'energy_pJ': energy_pJ,
            'energy_per_mac': energy_pJ/macs,
            'macs': macs,
            'energy_breakdown_pJ': energy_breakdown_pJ
        }
    else:
        output = {}

    return output

def main():
    parser = argparse.ArgumentParser(
            description='A simple tool for generating pickle files from timeloop output.')
    parser.add_argument('infile', nargs='?', default=xml_file_name, type=str,
            help='raw Timeloop XML output file')
    parser.add_argument('outfile', nargs='?', default='timeloop-output.pkl', type=argparse.FileType('wb'),
            help='write the output of infile to outfile')
    options = parser.parse_args()

    infile = options.infile
    outfile = options.outfile

    output = parse_timeloop_stats(infile)
    with outfile:
        pickle.dump(output, outfile, pickle.HIGHEST_PROTOCOL)
    print('Wrote output to %s.' % (outfile.name))

if __name__ == '__main__':
    main()
