import {feedback, field} from '../components/common/fields.js';
import {empty, metrics, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {STATUS} from '../constants/enums.js';
import {handler, poll} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, h, link, p} from '../utils/dom.js';

function comparisonForm(spec, datasets) {
  const settings = spec.comparison;
  const message = feedback();
  const submit = button('发起差异归因', {type:'submit', class:'primary', 'data-testid':'start-comparison'});
  const options = selected => datasets.map(item => el('option', {
    value:item.id, selected:String(item.id) === String(selected)}, `${item.name} · ${item.row_count} 行`));
  const newest = datasets[0], previous = datasets[1];
  return el('form', {class:'fields', 'data-testid':'comparison-form', onSubmit:handler(submit, message, async event => {
    const data = new FormData(event.target);
    const item = await workspace.startComparison({
      name:data.get('name'), period:data.get('period'),
      old_dataset_id:Number(data.get('old_dataset_id')), new_dataset_id:Number(data.get('new_dataset_id')),
    });
    location.hash = `#compare/${item.id}`;
  })},
    field({key:'name', label:'对比名称', type:'string', max_length:120}, `样本${settings.label}`),
    el('div', {class:'form-grid'},
      field({key:'period', label:'统计月份', type:'string', max_length:7, default:settings.default_period,
        help:'填写 YYYY-MM，两批记录都只取该自然月。'}),
      el('label', {class:'field', for:'old-dataset-id'}, el('span', {}, '旧批次'),
        el('select', {id:'old-dataset-id', name:'old_dataset_id', required:true}, options(previous?.id))),
      el('label', {class:'field', for:'new-dataset-id'}, el('span', {}, '新批次'),
        el('select', {id:'new-dataset-id', name:'new_dataset_id', required:true}, options(newest?.id))),
    ),
    el('p', {class:'subtle'}, '发起时锁定所选批次。之后补传的批次不会进入本次在途计算。'),
    el('div', {class:'actions'}, submit), message);
}

function resultView(job) {
  const result = job.result;
  return el('section', {class:'analysis', 'data-testid':'comparison-complete'},
    el('div', {class:'result-head'}, p(job.name, 'eyeline'), h(2, result.headline), p(result.note, 'intro-copy'),
      pill(STATUS[job.status], job.status)),
    metrics(result.metrics),
    (result.sections || []).map(item => panel(item.title, p(item.text))),
    result.tables.map(item => panel(item.title, table(item.columns, item.rows, {caption:item.title, pageSize:10}))));
}

function waiting(job) {
  return el('section', {class:'analysis'}, panel(job.name, pill(STATUS[job.status], job.status),
    p(job.status === 'failed' ? job.error || '对比失败，请检查两个批次的口径。' : '后台正在计算差异归因，完成后会自动展示。',
      job.status === 'failed' ? 'feedback' : 'subtle'),
    link('切换对比记录', '#compare', {class:'quiet'})));
}

export async function comparePage(route, refresh) {
  const {spec, datasets} = workspace;
  if (!session.canWrite) {
    return panel(spec.pages[6], empty('差异归因仅对分析员和复核主管开放。', '#delivery', spec.pages[5]));
  }
  const settings = spec.comparison;
  const items = await workspace.comparisons();
  const id = route.id || items[0]?.id;
  const job = id ? await workspace.getComparison(id) : null;
  const ready = datasets.length >= 2;
  const form = ready ? comparisonForm(spec, datasets)
    : empty('差异归因至少需要两个数据批次。', '#inputs', '前往导入');
  if (job && job.status !== 'complete' && job.status !== 'failed') {
    const original = location.hash;
    poll(() => workspace.getComparison(id), item => item.status === 'complete' || item.status === 'failed',
      () => location.hash === original)
      .then(result => { if (result && location.hash === original) refresh(); })
      .catch(() => {});
  }
  const history = el('ul', {class:'method-list'}, items.slice(0, 12).map(item =>
    el('li', {}, link(item.name, `#compare/${item.id}`), ' ', pill(STATUS[item.status], item.status))));
  return el('div', {class:'two-col'},
    el('div', {class:'wide-panel'},
      job ? (job.status === 'complete' && job.result ? resultView(job) : waiting(job))
        : panel(settings.label, p(settings.subtitle, 'intro-copy'), form)),
    el('aside', {class:'sidebar-panel'},
      job && panel('发起新的对比', p('每次对比都在发起时锁定新旧批次。', 'subtle'), form),
      panel('对比记录', items.length ? history : p('还没有对比记录。', 'empty')),
      panel('归因口径', el('ul', {class:'method-list'}, settings.methodology.map(text => el('li', {}, text))))));
}
