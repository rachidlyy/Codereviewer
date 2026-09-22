import { ArrowLeft, Github, Mail, Globe } from 'lucide-react';
import { useState } from 'react';

import iguidi from '../assets/IMG_6744.JPG';

type Props = {
  onBack: () => void;
  onStart: () => void;
};

type Lang = 'en' | 'zh';

const STACK: { layer: string; tech: string }[] = [
  { layer: 'Frontend', tech: 'React · TypeScript · Vite · Monaco' },
  { layer: 'Backend', tech: 'Python · FastAPI · Uvicorn' },
  { layer: 'AI', tech: 'Gemini (REST) with a Groq fallback' },
  { layer: 'Data', tech: 'In-memory structures — no database' },
  { layer: 'Execution', tech: 'Local Python subprocesses, per-test timeouts' },
];

const FLOW_EN = ['Problem', 'Code', 'Run', 'Test results', 'AI review', 'Improve'];
const FLOW_ZH = ['选题', '编码', '运行', '测试结果', 'AI 评审', '改进'];

type Copy = {
  back: string;
  eyebrow: string;
  heroTitle1: string;
  heroTitleAccent: string;
  heroTitle2: string;
  lede: string;
  workflowH: string;
  workflowP: string;
  whyH: string;
  cards: { title: string; body: string }[];
  stackH: string;
  problemsH: string;
  problemsP: string;
  problemNotes: Record<string, string>;
  teamH: string;
  teamP: string;
  teamRoles: string[];
  teamSupervisorNote: string;
  placementH: string;
  placementBody1: string;
  placementBody2: string;
  ctaH: string;
  ctaP: string;
  ctaBtn: string;
  source: string;
  contact: string;
};

const COPY: Record<Lang, Copy> = {
  en: {
    back: 'Back to problems',
    eyebrow: 'About',
    heroTitle1: 'A coding practice platform that ',
    heroTitleAccent: 'explains your code',
    heroTitle2: ', not just your score.',
    lede: 'CodeReviewer runs your Python against real test cases, then hands the results to an AI mentor that reviews your solution the way a senior engineer would — what works, what doesn\u2019t, and what to try next.',
    workflowH: 'The workflow',
    workflowP:
      'The whole product is one loop. Everything else is in service of making that loop fast enough to run a hundred times.',
    whyH: 'Why it exists',
    cards: [
      {
        title: 'Passing tests is not learning',
        body: 'A green check tells you a solution is correct. It doesn\u2019t tell you it\u2019s readable, that it handles the edge cases you skipped, or that it won\u2019t fall over on a 20,000-element input. The review step exists to close that gap.',
      },
      {
        title: 'Feedback should be concrete',
        body: 'Reviews reference your actual test results — the exact case that failed, the input that caused it, and the complexity of what you wrote. No generic advice.',
      },
      {
        title: 'One workflow, finished',
        body: 'This is a one-week MVP. It ships a single complete, demonstrable path rather than a broad platform where every feature is half-built.',
      },
    ],
    stackH: 'Stack',
    problemsH: 'Problems',
    problemsP: 'Five problems ship with the MVP, each with three to four test cases.',
    problemNotes: { '1': 'includes a 20,000-element performance case' },
    teamH: 'The team',
    teamP:
      'Five people built this in ten days. Each owned a slice of the stack end to end.',
    teamRoles: [
      'Auth · user history & data · sandbox & virtualization for compiling and running code using a VM instead of a local machine',
      'Full-stack · continuous code integration',
      'Compiler setup · language handling · frontend',
      'UI / UX',
    ],
    teamSupervisorNote: 'Supervisor · guiding the team',
    placementH: 'Built during a manufacturing practice placement',
    placementBody1:
      'CodeReviewer was developed as the deliverable for a ten-day manufacturing practice at Hangzhou Zhiluo Technology Co., Ltd. (杭州智络科技有限公司), 14–24 September 2025, as part of the Computer Science programme at China Jiliang University (中国计量大学).',
    placementBody2:
      'The work followed a full software process — Git setup, analysis and design, development, testing — documented in the practice report and the daily practice log.',
    ctaH: 'Try it',
    ctaP: 'No account needed to run code. Sign in to keep your history.',
    ctaBtn: 'Browse problems',
    source: 'Source',
    contact: 'Contact',
  },
  zh: {
    back: '返回题目列表',
    eyebrow: '关于',
    heroTitle1: '一个不仅给出分数，',
    heroTitleAccent: '更解释你的代码',
    heroTitle2: '的编程练习平台。',
    lede: 'CodeReviewer 会用真实的测试用例运行你的 Python 代码，然后把结果交给一位 AI 导师——它会像资深工程师一样评审你的解法：哪里对、哪里不对、下一步该尝试什么。',
    workflowH: '工作流',
    workflowP:
      '整个产品就是一个循环。其它的一切，都是为了让这个循环快到足以重复一百次。',
    whyH: '为什么做它',
    cards: [
      {
        title: '通过测试并不等于学会',
        body: '一个绿色的对勾只说明解法是正确的，却不会告诉你它是否易读、是否覆盖了你跳过的边界情况、或者它能否承受两万个元素的输入。评审这一步就是为了填补这段空白。',
      },
      {
        title: '反馈必须具体',
        body: '评审会引用你真实的测试结果——具体是哪一条用例失败、导致失败的输入是什么、你写出的代码复杂度如何。绝不给泛泛而谈的建议。',
      },
      {
        title: '一条完整的工作流',
        body: '这是一周完成的 MVP。它交付的是一条完整、可演示的路径，而不是一个每个功能都只做了一半的庞大平台。',
      },
    ],
    stackH: '技术栈',
    problemsH: '题目',
    problemsP: 'MVP 内置五道题目，每道包含三到四个测试用例。',
    problemNotes: { '1': '包含一个两万元素的性能用例' },
    teamH: '团队成员',
    teamP: '五个人，十天，共同完成。每个人都端到端地负责了技术栈中的一块。',
    teamRoles: [
      '认证 · 用户历史与数据 · 使用虚拟机代替本地环境来编译和运行代码的沙箱与虚拟化',
      '全栈 · 持续代码集成',
      '编译器搭建 · 多语言处理 · 前端',
      'UI / UX',
    ],
    teamSupervisorNote: '指导老师 · 团队指导',
    placementH: '诞生于一次生产实习',
    placementBody1:
      'CodeReviewer 是中国计量大学信息工程学院计算机专业为期十天的生产实习成果，实习单位为杭州智络科技有限公司，时间为 2025 年 9 月 14 日至 9 月 24 日。',
    placementBody2:
      '整个工作遵循了完整的软件流程——Git 配置、分析与设计、开发、测试——均记录在生产实习报告与每日实习日志中。',
    ctaH: '试一试',
    ctaP: '无需账号即可运行代码。登录后可保留你的历史记录。',
    ctaBtn: '浏览题目',
    source: '源码',
    contact: '联系',
  },
};

type Member = {
  name: string;
  handle: string;
  url?: string;
  img?: string; 
  /** Index into COPY[lang].teamRoles, or null for the supervisor. */
  roleIndex: number | null;
  supervisor?: boolean;
};

const TEAM: Member[] = [
  {
    name: 'javasigma',
    handle: '@javasigma',
    url: 'https://github.com/javasigma',
    img: iguidi,
    roleIndex: 0,
  },
  {
    name: 'rachidlyy',
    handle: '@rachidlyy',
    url: 'https://github.com/rachidlyy',
    roleIndex: 1,
  },
  {
    name: 'abdo666-max',
    handle: '@abdo666-max',
    url: 'https://github.com/abdo666-max',
    roleIndex: 2,
  },
  {
    name: 'jouubear',
    handle: '@jouubear',
    url: 'https://github.com/jouubear',
    roleIndex: 3,
  },
  {
    name: 'Wasim',
    handle: '',
    url: undefined,
    roleIndex: null,
    supervisor: true,
  },
];

export default function AboutPage({ onBack, onStart }: Props) {
  const [lang, setLang] = useState<Lang>('en');
  const t = COPY[lang];
  const flow = lang === 'en' ? FLOW_EN : FLOW_ZH;

  return (
    <main className="about-page">
      <div className="about-topbar">
        <button className="back" type="button" onClick={onBack}>
          <ArrowLeft size={14} />
          {t.back}
        </button>

        <div className="lang-toggle" role="group" aria-label="Language">
          <Globe size={13} className="lang-icon" />
          <button
            type="button"
            className={lang === 'en' ? 'lang-btn active' : 'lang-btn'}
            onClick={() => setLang('en')}
            aria-pressed={lang === 'en'}
          >
            EN
          </button>
          <button
            type="button"
            className={lang === 'zh' ? 'lang-btn active' : 'lang-btn'}
            onClick={() => setLang('zh')}
            aria-pressed={lang === 'zh'}
          >
            中文
          </button>
        </div>
      </div>

      <section className="about-hero">
        <p className="eyebrow">{t.eyebrow}</p>
        <h1>
          {t.heroTitle1}
          <span>{t.heroTitleAccent}</span>
          {t.heroTitle2}
        </h1>
        <p className="about-lede">{t.lede}</p>
      </section>

      <section className="about-section">
        <h2>{t.workflowH}</h2>
        <p className="about-copy">{t.workflowP}</p>
        <ol className="about-flow">
          {flow.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>

      <section className="about-section">
        <h2>{t.whyH}</h2>
        <div className="about-grid">
          {t.cards.map((card) => (
            <article className="about-card" key={card.title}>
              <h3>{card.title}</h3>
              <p>{card.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="about-section">
        <h2>{t.stackH}</h2>
        <dl className="about-stack">
          {STACK.map(({ layer, tech }) => (
            <div className="about-stack-row" key={layer}>
              <dt>{layer}</dt>
              <dd>{tech}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="about-section">
        <h2>{t.problemsH}</h2>
        <p className="about-copy">{t.problemsP}</p>
        <ul className="about-problems">
          <li>
            <b>Contains Duplicate</b>
            <span className="difficulty easy">Easy</span>
            {t.problemNotes['1'] && (
              <span className="about-note">{t.problemNotes['1']}</span>
            )}
          </li>
          <li>
            <b>Two Sum</b>
            <span className="difficulty easy">Easy</span>
          </li>
          <li>
            <b>Valid Anagram</b>
            <span className="difficulty easy">Easy</span>
          </li>
          <li>
            <b>Binary Search</b>
            <span className="difficulty easy">Easy</span>
          </li>
          <li>
            <b>Maximum Subarray</b>
            <span className="difficulty medium">Medium</span>
          </li>
        </ul>
      </section>

      <section className="about-section">
        <h2>{t.teamH}</h2>
        <p className="about-copy">{t.teamP}</p>
        <ul className="team-grid">
          {TEAM.map((member) => {
            const role =
              member.roleIndex !== null
                ? t.teamRoles[member.roleIndex]
                : t.teamSupervisorNote;
            const Card = member.url ? 'a' : 'div';
            return (
              <li key={member.name}>
                <Card
                  className={
                    member.supervisor ? 'team-card supervisor' : 'team-card'
                  }
                  {...(member.url
                    ? {
                        href: member.url,
                        target: '_blank',
                        rel: 'noopener noreferrer',
                      }
                    : {})}
                >
   <div className="team-avatar" aria-hidden="true">
  {member.img && <img src={member.img} alt="" />}
</div>
                  <div className="team-body">
                    <div className="team-name-row">
                      <span className="team-name">{member.name}</span>
                      {member.url && (
                        <span className="team-handle">
                          <Github size={12} />
                          {member.handle}
                        </span>
                      )}
                    </div>
                    <p className="team-role">{role}</p>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="about-section">
        <h2>{t.placementH}</h2>
        <p className="about-copy">{t.placementBody1}</p>
        <p className="about-copy">{t.placementBody2}</p>
      </section>

      <section className="about-cta">
        <div>
          <h2>{t.ctaH}</h2>
          <p>{t.ctaP}</p>
        </div>
        <button type="button" className="cta" onClick={onStart}>
          {t.ctaBtn}
        </button>
      </section>

      <footer className="about-footer">
        <a className="about-meta" href="#" onClick={(e) => e.preventDefault()}>
          <Github size={14} />
          {t.source}
        </a>
        <a
          className="about-meta"
          href="mailto:"
          onClick={(e) => e.preventDefault()}
        >
          <Mail size={14} />
          {t.contact}
        </a>
      </footer>
    </main>
  );
}