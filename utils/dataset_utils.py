"""
Utilities for formatting and saving hdf5 calibration data.
"""

import numpy as np
import matplotlib.pyplot as plt
import re
import h5py


def extract_solutions(file_path):
    """
    Load CASA bandpass calibration text output and split into its multiple solutions.

    Input:
        file_path: path to the CASA bandpass calibration text file.

    Output:
        solutions: list of solutions, each solution is a list of strings (lines).
    """
    with open(file_path, 'r') as file:
        lines = file.readlines()

    solutions_split = []

    for i, L in enumerate(lines):
        if "SpwID" in L:
            solutions_split.append(i)

    solutions = []

    if len(solutions_split) > 1:
        for i in range(len(solutions_split)-1):
            sol = lines[solutions_split[i]:solutions_split[i+1]]
            solutions.append(sol)
        solutions.append(lines[solutions_split[-1]:])
    else:
        solutions.append(lines[solutions_split[0]:])
    
    return solutions


def get_antenna_names(section):
    """
    Extract antenna names from a section of CASA bandpass calibration table.
    
    Input:
        section: A section of the calibration table starting with the antenna header line.

    Output:
        antenna_names: list of antenna names.
    """
    header_line = section[0]
    antenna_names = re.findall(r'Ant = ([a-zA-Z0-9]+)', header_line)
    return antenna_names


def remove_newline_chars(solution):
    """
    Remove newline characters from a list of strings.
    """
    return [line.rstrip('\n') for line in solution]


def remove_duplicate_heders(sol, last_header=None):
    """
    Remove duplicate antenna headers from the calibration solution iteratively.

    Input:
        sol: list of strings (lines) from the calibration solution.
        last_header: list of antenna names from the last header processed.

    Output:
        sol: list of strings (lines) without duplicate headers.
    """
    for i, L in enumerate(sol):
        if "Time" in L:
            current_header = get_antenna_names(sol[i-1:])
            if last_header is not None:
                if current_header == last_header and len(current_header) > 0:
                    sol = sol[:i-1] + sol[i+2:]
                    return remove_duplicate_heders(sol)
                
            last_header = current_header
    
    return sol


def split_into_sections(sol):
    """
    Split the calibration solution into sections based on unique antenna headers.
    Input:
        sol: list of strings (lines) from the calibration solution.

    Output:
        sections: table sections starting with the antenna header line.
    """
    sections_split = []

    for i, L in enumerate(sol):
        if "Time" in L:
            # Start section in previous line
            sections_split.append(i-1)
            
    sections = []
    for i in range(len(sections_split)-1):
        sect = sol[sections_split[i]:sections_split[i+1]]
        sections.append(sect)
    sections.append(sol[sections_split[-1]:])

    return sections


def join_sections(sections):
    """
    Join sections of the calibration solution into a single table, horizontally.

    Input:
        sections: list of sections of the calibration solution.

    Output:
        table: calibration table with a single antenna header line.
    """
    if len(sections) == 1:
        return sections[0][:2] + sections[0][3:]
    else:
        table = []
        for L, M in zip(sections[0], sections[1]):
            if M[0] == '-nbsdfbkj':
                continue
            else:
                L = L + M.split('|',1)[1]
            table.append(L)
        return join_sections([table] + sections[2:])
    

def parse_bandpass_text(file):
    
    solutions = extract_solutions(file)
    if len(solutions) > 1:
        print(len(solutions), "solutions found. First solution processing...")
        sol = solutions[0]

    sol = remove_newline_chars(sol)

    sol = remove_duplicate_heders(sol)

    sol = remove_duplicate_heders(sol)     

    sections = split_into_sections(sol)

    caltable = join_sections(sections)

    return caltable

def caltable_to_dict(table, npol=2):
    """
    Parse formatted CASA bandpass calibration output into a structured 
    Python dictionary.

    Input:
        table: list of strings, each string is a line from the CASA bandpass 
            calibration output. The strings should be pre-processed to
            remove duplicate headers and all antennas should be included in each line.
            Each line represents data for a different frequency channel.

        npol: number of polarizations (default is 2).

    Output dictionary:
        {
            'gains': array[ntime, nants, nchans, npol]  (complex)
            'antennas': [...names...]
            'channels': [...]
            'polarizations': ['pol0', 'pol1']
            'times': [...]
            'fields': [...]
        }
    """

    # ------------------------------------------------------------------
    # 1) Extract antenna names
    # ------------------------------------------------------------------
    antennas = get_antenna_names(table)
    nants = len(antennas)

    # ------------------------------------------------------------------
    # 2) Extract data lines
    # ------------------------------------------------------------------
    # Expected structure: hh:mm:ss.sss <space> field_name <space> chan| data...
    data_re = re.compile(r"(\S+)\s+(\S+)\s+(\d+)\|(.*)")
    times = []
    fields = []
    channel_list = []
    amp_blocks = []
    phs_blocks = []

    for L in table:
        m = data_re.match(L)
        if not m:
            continue

        time = m.group(1)
        field = m.group(2)
        ch = int(m.group(3))
        rest = m.group(4)

        # Remove character F (flagged data)
        rest = rest.replace("F", "")

        # Extract numeric values
        nums = rest.split()

        # Each antenna has 4 values: (amp, phase)*2 pols
        expected = nants * 2 * npol
        if len(nums) != expected:
            print(f"Warning: Expected {expected} values per line, got {len(nums)}.")
            return None

        # Convert to numpy array and reshape
        values = np.array([float(x) for x in nums])
        arr = values[:expected].reshape(nants, npol, 2)   # nants × npol × (amp, phase)

        # Extract amplitude and phase
        amp_blocks.append(arr[:, :, 0])
        phs_blocks.append(arr[:, :, 1])

        # Record time, field and channel information
        times.append(time)
        fields.append(field)
        channel_list.append(ch)

    # ------------------------------------------------------------------
    # 3) Convert to numpy arrays
    # ------------------------------------------------------------------
    times = np.unique(np.array(times))
    fields = np.unique(np.array(fields))
    if len(times) * len(fields) != 1:
        print("Warning: processing data from multiple timestamps or fields.")

    channels = np.array(channel_list)
    amp = np.array(amp_blocks)     # shape (ntime, nants, pol)
    phs = np.array(phs_blocks)

    nchans = len(np.unique(channels))

    # ------------------------------------------------------------------
    # 4) Reshape into (ntime, nants, nchans, npol)
    # ------------------------------------------------------------------
    # Channels typically appear sorted, but we sort by channel index:
    sort_idx = np.argsort(channels)
    amp = amp[sort_idx]
    phs = phs[sort_idx]
    channels = channels[sort_idx]

    # Gains: convert Amp + Phase → complex
    gains = amp * np.exp(1j * np.deg2rad(phs))

    # Reshape to (nchans, nants, npol)
    gains = gains.reshape(nchans, nants, npol)

    # Now (nants, nchans, npol)
    gains = gains.swapaxes(0, 1)  
    
    # ------------------------------------------------------------------
    # Final dictionary
    # ------------------------------------------------------------------
    result = {
        "gains": gains,                       # complex array
        "antennas": antennas,
        "channels": channels,
        "polarizations": ["pol0", "pol1"],
        "times": times,
        "fields": fields
    }

    return result


###############################################################################
# 2) SAVE THE DICTIONARY TO HDF5
###############################################################################

def save_bandpass_hdf5(filename, caldict):
    """
    Store the parsed dictionary into HDF5 in a CASA/UVCal-compatible layout.
    """

    gains = caldict["gains"]     # (ntime, nants, nchans, npol)
    # flags = caldict["flags"]
    antennas = caldict["antennas"]
    channels = caldict["channels"]
    pols = caldict["polarizations"]
    times = caldict["times"]
    fields = caldict["fields"]

    with h5py.File(filename, "w") as f:

        grp = f.create_group("CALIBRATION/BANDPASS")

        grp.create_dataset("ANTENNA", data=np.array(antennas, dtype='S'))
        grp.create_dataset("CHANNEL", data=channels)
        grp.create_dataset("POLARIZATION", data=np.array(pols, dtype='S'))
        grp.create_dataset("TIME", data=np.array(times, dtype='S'))
        grp.create_dataset("FIELD", data=np.array(fields, dtype='S'))

        ggrp = grp.create_group("GAIN")
        ggrp.create_dataset("CPARAM", data=gains)
        # ggrp.create_dataset("FLAG", data=flags)

    print("Saved:", filename)

def inspect_bandpass_hdf5(hdf5_file_path):
    """
    Inspect the bandpass calibration data from HDF5 file.
    """
    # Open and inspect the HDF5 file
    with h5py.File(hdf5_file_path, "r") as f:
        print("Groups in HDF5 file:")
        for group in f.keys():
            print(" -", group)
        
        bandpass_grp = f["CALIBRATION/BANDPASS"]
        print("\nDatasets in BANDPASS group:")
        for dataset in bandpass_grp.keys():
            print(" -", dataset)
        
def plot_cal_data(hdf5_file_path, out_dir="." ,pol=0):
    """
    Plot the bandpass calibration data from HDF5 file.
    """
    f = h5py.File(hdf5_file_path, "r")

    gains = np.array(f['CALIBRATION/BANDPASS']['GAIN/CPARAM'])[:,:,pol]

    # index by maximum gain
    order = np.argsort(np.mean(gains, axis=1))

    # color map for each antenna
    colors = plt.cm.viridis(np.linspace(0, 1, len(f['CALIBRATION/BANDPASS']['ANTENNA'])))

    plt.figure(figsize=(12,5))
    for i, order_i in enumerate(order):
        antenna = f['CALIBRATION/BANDPASS']['ANTENNA'][order_i]
        plt.subplot(1,2,1)
        plt.plot(np.abs(gains[order_i,:]), label=antenna.decode(), color=colors[i])
        plt.title("Amplitude")
        plt.xlabel("Channel Index")
        plt.subplot(1,2,2)
        plt.plot(np.angle(gains[order_i,:])/np.pi*180, label=antenna.decode(), color=colors[i])
        plt.title("Phase (degrees)")
        plt.xlabel("Channel Index")
        
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig(out_dir + "/bandpass_calibration_plot.png")