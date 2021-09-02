#!/usr/bin/env python3
'''
Scan the file system to build a simulations manifest for the data portal.

Usage
-----
$ ./make_json.py --help
'''

import json
import argparse
from pathlib import Path
import os

from tqdm import tqdm
# These are needed to read the header
import abacusnbody.data.asdf
import asdf

# omissions:
# ICs don't quite fall in the redshift-product-ftype hierarchy
# MergerTest doesn't have the standard set of redshifts

#DEFAULT_ROOT = '/mnt/ceph/users/lgarrison/AbacusSummit'
DEFAULT_ROOT = os.environ['CFS'] + '/desi/cosmosim/Abacus'
DEFAULT_PRODUCTS = dict(halos=dict(path='{}/halos', ftypes=('halo_info','halo_rv_A','halo_pid_A','field_rv_A','field_pid_A')),
                        cleaning=dict(path='cleaning/{}', ftypes=('cleaned_halo_info','cleaned_rvpid')),
                        power=dict(path='power/{}', ftypes=('AB','pack9')),
                        )
                        #lightcones=('heal','pid','rv')  # TODO
DEFAULT_SIM_PATS = ('AbacusSummit_*/', 'small/AbacusSummit_*/')
<<<<<<< HEAD
DEFAULT_OUTFN = 'web/portal/static/data/simulations.json'
=======
DEFAULT_OUTFN = 'portal/static/data/simulations.json'
>>>>>>> 3d818e7053b5a3aafe859665e92da5a40143eb19

DEFAULT_REDSHIFTS = [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.575, 0.65, 0.725, 0.8, 0.875, 0.95, 1.025, 1.1, 1.175, 1.25, 1.325, 1.4, 1.475, 1.55, 1.625, 1.7, 1.85, 2.0, 2.25, 2.5, 2.75, 3.0, 5.0, 8.0]

def find_products(simdir, products, redshifts):
    j = {}
    header = {}
    for prod in products:
        j[prod] = {}  # j['halos']
        pdir = simdir.parent / products[prod]['path'].format(simdir.name)
        for zdir in sorted(pdir.glob('z*/')):
            zval = zdir.name[1:]
            zval = float(zval)
            assert zval in DEFAULT_REDSHIFTS
            if zval not in redshifts:
                continue
            j[prod][zval] = {}  # j['halos']['0.100']
            for ftype in products[prod]['ftypes']:
                if (fpath:=zdir/ftype).is_dir():
                    du = [fn.stat().st_size for fn in fpath.iterdir()]
                    nfile = len(du)
                    du = f'{sum(du):.3g}'  # round to save characters
                    j[prod][zval][ftype] = [nfile,du]  # j['halos']['0.100']['halo_info']

                    if not header:
                        try:
                            with asdf.open(next(fpath.glob('*.asdf'))) as af:
                                for k in ('BoxSize','SimComment','ParticleMassHMsun'):
                                    header[k] = af['header'][k]

                                header['PPD'] = int(round(af['header']['NP']**(1/3)))
                        except Exception as e:
                            raise Exception(f'Failed in: {fpath}') from e
                            
            # this z not on disk?
            if not j[prod][zval]:
                del j[prod][zval]
        # no halos?
        if not j[prod]:
            del j[prod]
    # no products?
    if not j:
        return None
    
    j['header'] = header
    return j
    

def main(sim_pats=DEFAULT_SIM_PATS,
         products=DEFAULT_PRODUCTS,
         root=DEFAULT_ROOT,
         out=DEFAULT_OUTFN,
         redshifts=DEFAULT_REDSHIFTS,
         compact=True,
        ):
    root = Path(root)
    
    sims = []
    for pat in sim_pats:
        sims += root.glob(pat)
    
    rows = []  # d['AbacusSummit_base_c000_ph000']['halos']['z0.100']['halo_info']
    
    for sim in tqdm(sorted(sims)):
        sim = Path(sim)
        
        row = find_products(sim, products, redshifts)
        if row:
            row.update({'name': sim.name,
                        'root': str(sim.relative_to(root)),
                        })
            rows += [row]
    
    # add the index to each row
    for uid,row in enumerate(rows):
        row['id'] = uid
            
    # figure out which z we actually have any data for
    redshifts = list(sorted(set(sum((sum( (list(row.get(prod,[])) for row in rows),[]) for prod in products),[] ))))
    print(len(redshifts), redshifts)
    
    manifest = {'data':rows,
                'redshifts':redshifts,
                # TODO
                'products':products}
    
    if compact:
        jsargs = dict(separators=(',', ':'))
    else:
        jsargs = dict(indent=4)
    s = json.dumps(manifest, **jsargs)
    #print(s)
    with open(out, 'w', encoding='utf-8') as fp:
        fp.write(s)


class ArgParseFormatter(argparse.RawDescriptionHelpFormatter,
                        argparse.ArgumentDefaultsHelpFormatter):
    pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=ArgParseFormatter)
    #parser.add_argument('sims', help='Simulation', nargs='+', metavar='SIM')
    parser.add_argument('-o','--out', help='Output JSON file', default=DEFAULT_OUTFN)

    args = parser.parse_args()
    args = vars(args)

    main(**args)
