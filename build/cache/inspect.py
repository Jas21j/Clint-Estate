import bpy, json
from collections import Counter
out={}
for name in ("Roof_Slab","L0_Walls","L1_Slab"):
    ob=bpy.data.objects[name]; me=ob.data
    c=Counter()
    for p in me.polygons:
        d='up' if p.normal.z>0.9 else 'down' if p.normal.z<-0.9 else 'side'
        c[(d, me.materials[p.material_index].name)]+=1
    out[name]={f"{k[0]}:{k[1]}":v for k,v in c.items()}
    out[name]['mats']=[m.name for m in me.materials]
out['diffuse']={m.name:[round(x,2) for x in m.diffuse_color] for m in bpy.data.materials if m.name in ('Roof','Wall','WallTop','Slab')}
out['furn_count']=Counter(o.get('piece') for o in bpy.data.objects if o.type=='EMPTY' and o.get('kind')=='furniture' and o.get('piece'))
out['light_dir']=list(bpy.context.scene.display.light_direction)
print("JSON"+json.dumps(out,default=str))
