import './skills.css';
export type SkillDependency={id:string;version:string};
export function SkillDependencies({items}:{items?:SkillDependency[]}){
  const unique=[...new Map((items||[]).map(item=>[item.id+'@'+item.version,item])).values()];
  return unique.length?<small className="skill-dependencies">依赖：{unique.map(item=>item.id+' v'+item.version).join('、')}；需在本项目同时启用精确版本，安装不会自动启用。</small>:null;
}
