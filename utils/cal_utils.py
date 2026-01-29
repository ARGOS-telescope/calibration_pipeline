"""
Utilities for calibration pipeline. 
"""
from casatasks import (
    listobs, flagdata, initweights, setjy,
    gaincal, bandpass, fluxscale, applycal, split, listcal
)
from casatools import msmetadata


def detect_fields_by_index(vis):
    """Detect key fields and return their field IDs using CASA msmetadata.

    Uses msmd.fieldsforname(name) to obtain authoritative field IDs. This avoids
    off-by-one errors that can arise from naive enumeration of field names.
    """
    msmd = msmetadata()
    msmd.open(vis)
    all_field_names = msmd.fieldnames()

    def first_field_id_for(name):
        ids = msmd.fieldsforname(name)
        if ids is None:
            return None
        # Prefer a field ID that actually has scans/rows; fall back to first
        try:
            for fid in list(ids):
                try:
                    scans = msmd.scansforfield(int(fid))
                    if scans is not None and len(scans) > 0:
                        return int(fid)
                except Exception:
                    # If scansforfield not available or fails, try timesforfield
                    try:
                        times = msmd.timesforfield(int(fid))
                        if times is not None and len(times) > 0:
                            return int(fid)
                    except Exception:
                        continue
            # Fallback to the first ID if none of the above checks succeeded
            return int(list(ids)[0])
        except TypeError:
            return int(ids)

    def field_id_for_intents(intent_candidates):
        for intent in intent_candidates:
            try:
                ids = msmd.fieldsforintent(intent)  # may be ndarray or list
            except Exception:
                ids = None
            if ids is None:
                continue
            for fid in list(ids):
                try:
                    scans = msmd.scansforfield(int(fid))
                    if scans is not None and len(scans) > 0:
                        return int(fid)
                except Exception:
                    try:
                        times = msmd.timesforfield(int(fid))
                        if times is not None and len(times) > 0:
                            return int(fid)
                    except Exception:
                        continue
        return None

    # Prefer intents (if present), otherwise fall back to known names
    fluxcal = field_id_for_intents([
        "CALIBRATE_FLUX", "FLUX", "AMPLITUDE", "CALIBRATE_AMPLI"
    ]) or first_field_id_for("J1331+3030")

    bandcal = field_id_for_intents([
        "CALIBRATE_BANDPASS", "BANDPASS"
    ]) or first_field_id_for("J1229+0203") or first_field_id_for("J1008+0730")

    phasecal = field_id_for_intents([
        "CALIBRATE_PHASE", "PHASE"
    ]) or first_field_id_for("J0954+1743")

    target = field_id_for_intents([
        "TARGET", "OBSERVE_TARGET#ON_SOURCE"
    ]) or first_field_id_for("IRC+10216")

    print("\n=== Available fields (by ID) ===")
    for idx, name in enumerate(all_field_names):
        print(f"  {idx}: {name}")

    print("\n=== Selected fields (IDs) ===")
    print(f"  Flux calibrator  : {fluxcal}")
    print(f"  Bandpass cal     : {bandcal}")
    print(f"  Phase calibrator : {phasecal}")
    print(f"  Science target   : {target}")

    msmd.close()

    # Validate and fail fast with actionable message
    missing = []
    if fluxcal is None:
        missing.append("J1331+3030 (fluxcal)")
    if bandcal is None:
        missing.append("J1008+0730 (bandcal)")
    if phasecal is None:
        missing.append("J0954+1743 (phasecal)")
    if target is None:
        missing.append("IRC+10216 (target)")
    if missing:
        raise RuntimeError(
            "Could not locate required fields in MS: "
            + ", ".join(missing)
            + ".\nCheck field names in your dataset (see printed list above) "
              "and update the expected names if they differ."
        )

    return dict(fluxcal=fluxcal, bandcal=bandcal, phasecal=phasecal, target=target)


def calibrate_vla_dataset(vis="day2_TDEM0003_10s_norx.ms", out_dir="data"):
    """Perform full calibration on the VLA dataset."""
    fields = detect_fields_by_index(vis)
    fluxcal = fields["fluxcal"]
    bandcal = fields["bandcal"]
    phasecal = fields["phasecal"]
    target = fields["target"]

    # Convert all field indices to strings for CASA
    fluxcal_str = str(fluxcal)
    bandcal_str = str(bandcal)
    phasecal_str = str(phasecal)
    target_str = str(target)

    # Calibration table names
    gcal_bp_p = "gaincal_bp_p.cal"
    gcal_ap_comb = "gaincal_ap_comb.cal"
    bcal = "bandpass.cal"
    fcal = "fluxscale.cal"
    outvis = "calibrated_target.ms"
    caltable_name = out_dir + "/caltable_bandpass.txt"

    # Reference antenna (can be automated if needed)
    refant = "ea01"

    print("\n=== Step 1: Inspect observation summary ===")
    listobs(vis=vis, listfile="listobs.txt", overwrite=True)

    print("\n=== Step 2: Basic flagging ===")
    flagdata(vis=vis, mode='manual', autocorr=True)
    flagdata(vis=vis, mode='shadow', flagbackup=False)

    print("\n=== Step 3: Initialise weights ===")
    initweights(vis=vis, wtmode='nyq', dowtsp=True)

    print("\n=== Step 4: Set flux model ===")
    setjy(vis=vis, field=fluxcal_str, standard='Perley-Butler 2017')

    print("\n=== Step 5: Solve for phase-only gains on bandpass calibrator ===")
    gaincal(vis=vis, caltable=gcal_bp_p, field=bandcal_str, solint='int',
            refant=refant, calmode='p')

    print("\n=== Step 6: Solve for bandpass ===")
    bandpass(vis=vis, caltable=bcal, field=bandcal_str, solint='inf',
             combine='scan', refant=refant, gaintable=[gcal_bp_p])

    print("\n=== Step 7: Solve for complex gains on flux and phase calibrators (combined) ===")
    gaincal(vis=vis, caltable=gcal_ap_comb, field=fluxcal_str, solint='int',
            refant=refant, calmode='ap', gaintable=[bcal])
    gaincal(vis=vis, caltable=gcal_ap_comb, field=phasecal_str, solint='int',
            refant=refant, calmode='ap', gaintable=[bcal], append=True)

    print("\n=== Step 8: Bootstrap flux scale ===")
    fluxscale(vis=vis, caltable=gcal_ap_comb, fluxtable=fcal,
              reference=fluxcal_str, transfer=phasecal_str)

    print("\n=== Step 9: Apply calibration to target ===")
    applycal(vis=vis, field=target_str, gaintable=[bcal, fcal],
             interp=['linear,linear', 'linear'], calwt=True,
             applymode='calonly')

    print("\n=== Step 10: Split out calibrated target data ===")
    split(vis=vis, outputvis=outvis, field=target_str, datacolumn='corrected')

    print("\n=== Step 11: Export caltable ===")
    listcal(vis=vis, caltable=bcal, field=bandcal_str, listfile=caltable_name)

    print(f"\n✅ Calibration complete. Caltable saved to {caltable_name}")

    return caltable_name


def calibrate_meerkat_dataset(vis="1766058131-sdp-l0_2026-01-15T11-39-25_a25.ms", out_dir="data"):
    """Perform calibration on the MeerKAT dataset."""
    # The MeerKAT calibration dataset contains a single field
    fluxcal_str = "0"
    bandcal_str = "0"

    # Calibration table names
    gcal_bp_p = "gaincal_bp_p.cal"
    gcal_ap_comb = "gaincal_ap_comb.cal"
    bcal = "bandpass.cal"
    caltable_name = out_dir + "/caltable_bandpass.txt"
    gcal_delay = "delay.cal"

    # Reference antenna (can be automated if needed)
    refant = "m063"

    print("\n=== Step 1: Inspect observation summary ===")
    listobs(vis=vis, listfile="listobs.txt", overwrite=True)

    print("\n=== Step 2: Basic flagging ===")
    flagdata(vis=vis, mode='manual', autocorr=True)
    flagdata(vis=vis, mode='shadow', flagbackup=False)
    flagdata(vis=vis, mode='manual', spw='0:0~10')
    flagdata(vis=vis, mode='manual', spw='0:119')
    flagdata(vis=vis, mode='manual', spw='0:166~182')
    flagdata(vis=vis, mode='manual', spw='0:252')
    flagdata(vis=vis, mode='manual', spw='0:320')
    flagdata(vis=vis, mode='manual', spw='0:609')
    flagdata(vis=vis, mode='manual', spw='0:768')

    print("\n=== Step 3: Initialise weights ===")
    initweights(vis=vis, wtmode='nyq', dowtsp=True)

    print("\n=== Step 4: Set flux model ===")
    setjy(vis=vis, field=fluxcal_str, standard='Perley-Butler 2010')

    print("\n=== Step 5: Solve for delays on bandpass calibrator ===")
    gaincal(vis=vis, caltable=gcal_delay, field=bandcal_str,
    solint='inf', refant=refant, gaintype='K')

    print("\n=== Step 6: Solve for phase-only gains on bandpass calibrator ===")
    gaincal(vis=vis, caltable=gcal_bp_p, field=bandcal_str, solint='int',
            refant=refant, calmode='p', gaintable=[gcal_delay])

    print("\n=== Step 7: Solve for bandpass ===")
    bandpass(vis=vis, caltable=bcal, field=bandcal_str, solint='inf',
             combine='scan', refant=refant, gaintable=[gcal_delay, gcal_bp_p])

    print("\n=== Step 8: Solve for complex gains on flux and phase calibrators (combined) ===")
    gaincal(vis=vis, caltable=gcal_ap_comb, field=fluxcal_str, solint='int',
            refant=refant, calmode='ap', gaintable=[gcal_delay, bcal])

    print("\n=== Step 9: Export caltable ===")
    listcal(vis=vis, caltable=bcal, field=bandcal_str, listfile=caltable_name)

    print(f"\n✅ Calibration complete. Caltable saved to {caltable_name}")

    return caltable_name
