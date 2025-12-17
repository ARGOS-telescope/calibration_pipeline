#!/usr/bin/env python3
"""
CASA 6 automatic VLA calibration with automatic field index selection.

- Automatically detects flux, bandpass, phase calibrators, and target.
- Selects the first field index for each unique field name.
- Fully compatible with pip-installed CASA 6.
- All field arguments converted to strings to satisfy CASA's requirements.
"""

# make utils module available module in /workspace/data/utils
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'data', 'utils')))

from cal_utils import calibrate_vla_dataset
from dataset_utils import parse_bandpass_text, caltable_to_dict, save_bandpass_hdf5, plot_cal_data


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="CASA VLA calibration with automatic field index selection."
    )
    parser.add_argument("--vis", type=str, default="day2_TDEM0003_10s_norx.ms",
                        help="Input Measurement Set (.ms)")
    parser.add_argument("--out_dir", type=str, default="/workspace/data/outputs", 
                        help="Output directory for calibration tables and plots, " \
                        "default: workspace/data/data")
    parser.add_argument("--out_file", type=str, default="caltable_bandpass.hdf5", 
                        help="Output HDF5 file for calibration data")
    args = parser.parse_args()

    cal_txt = calibrate_vla_dataset(vis=args.vis, out_dir=args.out_dir)

    caltable = parse_bandpass_text(cal_txt)

    caldict = caltable_to_dict(caltable)

    save_bandpass_hdf5(args.out_dir + "/" + args.out_file, caldict)

    plot_cal_data(args.out_dir + "/" + args.out_file, args.out_dir)

if __name__ == "__main__":
    main()
