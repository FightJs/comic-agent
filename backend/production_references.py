"""Compare the approval and adoption actually frozen with text-production assets."""
from fastapi import HTTPException


def state_stale(store,db,pid,assets):
    for asset in assets:
        if not isinstance(asset,dict) or any(k not in asset for k in ('id','version','adopted','review')):return True
        try:current=store.get(db,pid,asset['id'],asset['version'])
        except HTTPException as exc:
            if exc.status_code==404:return True
            raise
        if current['adopted']!=asset['adopted'] or current['review']!=asset['review']:return True
    return False
