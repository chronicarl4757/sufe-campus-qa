# 上财知识库覆盖审计

- question_bank_version: `sufe-question-bank.v1`
- question_bank_hash: `sha256:8a5ab6a1110531cd443d9e652a1032f4e97d25d0f083bf9728429a0c28c352f9`
- embedding_model: `BAAI/bge-m3`
- similarity_threshold: `0.5`
- index_fingerprint: `sha256:43554cb21eeb45f5cd669a742735b9a0aab5d5b5dfed27bea35d7bf3844ba7d4`
- evaluated_at: `2026-08-10T13:03:35+00:00`

## 场景统计

| 场景 | 文档数 | 有效 policy | 有效 procedure | 标题/不完整 | 新闻/宣传 | 最新有效版本 | 可回答 | 部分 | 不可回答 | 缺失权威来源 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 本科教务 | 52 | 14 | 19 | 0 | 0 | 22 | 17 | 3 | 0 | — |
| 研究生培养与学位 | 17 | 6 | 2 | 0 | 0 | 9 | 11 | 9 | 0 | — |
| 奖助学金 | 147 | 24 | 5 | 0 | 0 | 44 | 8 | 7 | 0 | — |
| 推免与招生 | 242 | 14 | 9 | 0 | 0 | 130 | 6 | 9 | 0 | — |
| 就业手续 | 76 | 0 | 7 | 1 | 0 | 37 | 7 | 8 | 0 | — |
| 宿舍后勤 | 10 | 0 | 3 | 1 | 0 | 3 | 5 | 5 | 0 | — |
| 信息化与校园卡 | 14 | 0 | 2 | 0 | 0 | 2 | 3 | 12 | 0 | — |
| 图书馆 | 9 | 0 | 4 | 0 | 0 | 4 | 6 | 4 | 0 | — |
| 医疗医保 | 74 | 8 | 40 | 0 | 0 | 46 | 6 | 4 | 0 | — |
| 国际交流 | 32 | 0 | 5 | 0 | 0 | 6 | 8 | 2 | 0 | — |
| 新生与安全 | 17 | 4 | 9 | 0 | 0 | 11 | 8 | 2 | 0 | — |

## 逐题结果

| ID | 问题 | 场景 | 状态 | doc_id | 标题 | 缺口 |
|---|---|---|---|---|---|---|
| jwc-leave-001 | 本科生因病无法参加考试如何申请缓考？ | 本科教务 | answerable | 36481bbba58c, 282827505b9c, f8892252b39b, caef95227715, b34e7552a58f | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-leave-002 | 本科生如何办理休学和复学？ | 本科教务 | answerable | 36481bbba58c, 3805d2ce561e, 6cc64e90571a, caef95227715, f8892252b39b | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-course-003 | 重修课程如何办理？ | 本科教务 | partially_answerable | 36481bbba58c, f8892252b39b, 6cc64e90571a, c5ae3d61e34e, 2e002b0c1101 | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | 缺少回答要点：适用情形 |
| jwc-major-004 | 如何申请转专业？ | 本科教务 | answerable | 36481bbba58c, 4cc221b5efe0, 6cc64e90571a, c5ae3d61e34e, fb93dacd6384 | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-credit-005 | 本科生如何申请校外学习学分认定？ | 本科教务 | answerable | 36481bbba58c, 6cc64e90571a, b73dbd658c3b, caef95227715, c5ae3d61e34e | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-card-006 | 学生证丢失如何补办？ | 本科教务 | answerable | 661167fb7bae, 36481bbba58c, a134102b3ff1, b34e7552a58f, caef95227715 | 13d98ab8-a7b8-4dd6-8bfe-c7189cf77bf1.doc | — |
| jwc-drop-007 | 退课和选课的办理入口是什么？ | 本科教务 | answerable | 36481bbba58c, 6cc64e90571a, f8892252b39b, caef95227715, fb93dacd6384 | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-double-008 | 本科生如何申请双专业学习？ | 本科教务 | answerable | 36481bbba58c, 6cc64e90571a, c5ae3d61e34e, 75094c370868, b73dbd658c3b | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-withdraw-009 | 本科生办理退学需要哪些手续？ | 本科教务 | answerable | 36481bbba58c, 3805d2ce561e, ce9f40abd3f5, d801506ea32e, 6cc64e90571a | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-exam-010 | 本科生考试违纪会按照什么规定处理？ | 本科教务 | partially_answerable | 36481bbba58c, a134102b3ff1, c5ae3d61e34e, caef95227715, fb93dacd6384 | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | 缺少回答要点：适用制度; 缺少回答要点：违纪类型 |
| jwc-score-011 | 本科生对课程成绩有异议如何申请复核？ | 本科教务 | answerable | 36481bbba58c, c5ae3d61e34e, caef95227715, fb93dacd6384, 1e34012f4414 | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-makeup-012 | 本科生补考和重修的区别是什么？ | 本科教务 | answerable | 36481bbba58c, f8892252b39b, 3805d2ce561e, 4cc221b5efe0, 6cc64e90571a | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-exempt-013 | 本科生课程免修或免考如何申请？ | 本科教务 | answerable | 36481bbba58c, 6cc64e90571a, c5ae3d61e34e, f8892252b39b, caef95227715 | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-plan-014 | 在哪里可以查询本科生培养方案和学分要求？ | 本科教务 | partially_answerable | 36481bbba58c, 6cc64e90571a, caef95227715, 59f10253846c, 75094c370868 | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | 缺少回答要点：课程类别; 缺少回答要点：适用年级 |
| jwc-thesis-015 | 本科毕业论文如何选题、开题和提交？ | 本科教务 | answerable | 75094c370868, 59f10253846c, 36481bbba58c, 1e34012f4414, 62024ec24ad1 | 上海财经大学本科学生毕业论文（设计）工作的规定.pdf | — |
| jwc-graduation-016 | 本科生申请毕业需要满足哪些学分和学籍条件？ | 本科教务 | answerable | 36481bbba58c, caef95227715, c5ae3d61e34e, 6cc64e90571a, f8892252b39b | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-gpa-017 | 本科成绩单中的绩点如何计算？ | 本科教务 | answerable | 36481bbba58c, 6cc64e90571a, a134102b3ff1, caef95227715, 75094c370868 | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-sports-018 | 体育特长生比赛加分如何申请？ | 本科教务 | answerable | b73dbd658c3b, 36481bbba58c, b34e7552a58f, caef95227715, 3805d2ce561e | 办事流程 | — |
| jwc-certificate-019 | 本科生如何办理在读或学籍证明？ | 本科教务 | answerable | 36481bbba58c, caef95227715, 3805d2ce561e, 6cc64e90571a, c5ae3d61e34e | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| jwc-contact-020 | 教务系统或选课出现问题应联系哪个部门？ | 本科教务 | answerable | 36481bbba58c, 75094c370868, c5ae3d61e34e, 59f10253846c, 6cc64e90571a | 上海财经大学本科学生学籍管理实施细则（修订稿）.pdf | — |
| gs-course-001 | 研究生如何选课？ | 研究生培养与学位 | answerable | 12d8bae93ae8, 1fb82cab054b, 31211fd84e31, 844338d7d8e8, 5150e284b7e6 | 上海财经大学2026年招收攻读硕士学位研究生初试成绩公布后相关问题汇总 | — |
| gs-grade-002 | 研究生是否有绩点要求？ | 研究生培养与学位 | partially_answerable | 739c8bdca878, bfe1c345a8e2, 1f9cd474ac62, 12d8bae93ae8, 1fb82cab054b | 2026年全国硕士研究生招生考试上海财经大学考点（代码：3109）考前提醒（二） | 缺少回答要点：适用培养层次; 缺少回答要点：适用环节; 缺少回答要点：制度来源 |
| gs-transcript-003 | 研究生成绩单在哪里打印？ | 研究生培养与学位 | answerable | 94bcb693271a, e364a11babc8, 5d4628bc8faa, b50750ea2d92, 20233e75a8e3 | 上海财经大学2025年硕士研究生招生考试报名公告 | — |
| gs-credit-004 | 研究生学分如何认定？ | 研究生培养与学位 | answerable | c55834842682, fdc14f69b3bb, f69ff958852a, 1a96324e5a8d, c8ae11c35f97 | 关于开展2023年研究生“学术之星”评选工作的通知 | — |
| gs-leave-005 | 研究生如何申请休学和复学？ | 研究生培养与学位 | partially_answerable | 12d8bae93ae8, a599138400a2, 844338d7d8e8, ccda2fd108a8, 1cdd885d171c | 上海财经大学2026年招收攻读硕士学位研究生初试成绩公布后相关问题汇总 | 缺少回答要点：学籍影响 |
| gs-phd-006 | 博士申请考核制流程是什么？ | 研究生培养与学位 | partially_answerable | c0c2a73030c1, 354be832f02e, 64b251126078, a50221cc7070, e7b6db0e6beb | 上海财经大学2026年少数民族高层次骨干人才计划研究生招生办法 | 缺少回答要点：考核环节 |
| gs-joint-007 | 硕博连读需要满足什么条件？ | 研究生培养与学位 | answerable | c0c2a73030c1, 354be832f02e, a50221cc7070, e6d269205cb4, 83b8da8365ee | 上海财经大学2026年少数民族高层次骨干人才计划研究生招生办法 | — |
| gs-defense-008 | 研究生学位论文答辩流程是什么？ | 研究生培养与学位 | partially_answerable | c8ae11c35f97, 18470ac98c09, 83b8da8365ee, c55834842682, fdc14f69b3bb | 上海财经大学博士研究生学位论文工作的基本要求（2002年9月修订） | 缺少回答要点：学位授予环节 |
| gs-exchange-009 | 研究生短期国际交流如何申请？ | 研究生培养与学位 | partially_answerable | f511bc1fc4a2, f8015ab6e16f, 220adadfc5cc, 0ee8ebbdf902, 26beb38fef3e | 上海财经大学关于做好2026年博士生导师短期出国交流项目申请工作的通知 | 缺少回答要点：项目对象; 缺少回答要点：资助或学分 |
| gs-scholarship-010 | 研究生国家奖学金依据哪份办法评定？ | 研究生培养与学位 | partially_answerable | a50221cc7070, e6d269205cb4, 83b8da8365ee, 0ee8ebbdf902, 26beb38fef3e | 上海财经大学关于2022年国家建设高水平大学公派研究生项目选拔及申请受理工作的安排 | 缺少回答要点：适用办法; 缺少回答要点：年度通知 |
| gs-plan-011 | 研究生培养方案和学分要求在哪里查询？ | 研究生培养与学位 | partially_answerable | 60f9a164fe20, 2675703133ac, 12d8bae93ae8, 844338d7d8e8, c8ae11c35f97 | 上海财经大学博士研究生中期考核办法 | 缺少回答要点：适用年级 |
| gs-opening-012 | 研究生学位论文开题报告如何办理？ | 研究生培养与学位 | answerable | c8ae11c35f97, a50221cc7070, 60f9a164fe20, 83b8da8365ee, 1c38828bd054 | 上海财经大学博士研究生学位论文工作的基本要求（2002年9月修订） | — |
| gs-midterm-013 | 研究生中期考核有哪些要求？ | 研究生培养与学位 | partially_answerable | 60f9a164fe20, 739c8bdca878, c0c2a73030c1, bfe1c345a8e2, 1f9cd474ac62 | 上海财经大学博士研究生中期考核办法 | 缺少回答要点：考核内容; 缺少回答要点：结果处理 |
| gs-degree-014 | 研究生申请学位需要提交哪些材料？ | 研究生培养与学位 | answerable | e2c59b1cc354, 2e1d67827a30, b1710c4f86d0, c845c6bbfc32, 18470ac98c09 | 上海财经大学2021年接收外校优秀应届本科毕业生免试攻读研究生办法 | — |
| gs-status-015 | 研究生在线学籍证明如何办理？ | 研究生培养与学位 | answerable | ccda2fd108a8, 1cdd885d171c, b566c11d3ea4, a599138400a2, ae54aac7e909 | 2025年全国硕士研究生招生上海财经大学报考点（代码：3109）报名公告 | — |
| gs-exemption-016 | 研究生免修免考如何申请？ | 研究生培养与学位 | answerable | e6d269205cb4, f900e2c94b7f, 12d8bae93ae8, c0c2a73030c1, 397ea76bef2e | 上海财经大学会计学院关于举办“第十一届全国优秀大学生夏令营”的通知 | — |
| gs-graduation-017 | 研究生毕业管理和离校手续有哪些？ | 研究生培养与学位 | answerable | a50221cc7070, c0c2a73030c1, 354be832f02e, 64b251126078, 1c38828bd054 | 上海财经大学关于2022年国家建设高水平大学公派研究生项目选拔及申请受理工作的安排 | — |
| gs-extension-018 | 研究生延期毕业如何申请？ | 研究生培养与学位 | answerable | c8ae11c35f97, f900e2c94b7f, 12d8bae93ae8, c0c2a73030c1, 1c38828bd054 | 上海财经大学博士研究生学位论文工作的基本要求（2002年9月修订） | — |
| gs-advisor-019 | 研究生如何申请导师变更？ | 研究生培养与学位 | partially_answerable | 12d8bae93ae8, 844338d7d8e8, 2675703133ac, f511bc1fc4a2, f8015ab6e16f | 上海财经大学2026年招收攻读硕士学位研究生初试成绩公布后相关问题汇总 | 缺少回答要点：适用情形 |
| gs-review-020 | 研究生学位论文外审和预答辩如何安排？ | 研究生培养与学位 | answerable | 83b8da8365ee, c8ae11c35f97, c55834842682, fdc14f69b3bb, f69ff958852a | 政策文件 | — |
| aid-national-001 | 本科生国家奖学金申请条件是什么？ | 奖助学金 | answerable | 3e2ec161e017, 861408385e90, 87cb45995557, 2e8a9386b4f8, 57d4620aea1b | 关于开展2024-2025学年国家励志奖学金评选工作的通知 | — |
| aid-fail-002 | 有挂科记录还能申请奖学金吗？ | 奖助学金 | partially_answerable | 52a785d3df9c, e8b2b9918594, 231d0aa11418, 77ec547b2f2e, 87cb45995557 | bb74c415-f49b-4bb8-9f0b-3830b36fb8cc.pdf | 缺少回答要点：适用奖项; 缺少回答要点：依据办法 |
| aid-hardship-003 | 家庭经济困难学生如何认定？ | 奖助学金 | answerable | 52a785d3df9c, b815e0eefe9a, 3e2ec161e017, 861408385e90, 77d10806304e | bb74c415-f49b-4bb8-9f0b-3830b36fb8cc.pdf | — |
| aid-temporary-004 | 临时困难补助如何申请？ | 奖助学金 | answerable | 04bec8770ea1, 58c34224a8c8, 5220cf43e76b, 1f5aa08edc4d, 52a785d3df9c | 关于印发《上海财经大学学生临时困难补助管理办法》的通知 | — |
| aid-workstudy-005 | 勤工助学有哪些要求？ | 奖助学金 | partially_answerable | 1f5aa08edc4d, 5220cf43e76b, 52a785d3df9c, d9ef5485306b, 3e2ec161e017 | 关于印发《上海财经大学学生违纪处分规定（2023年10月修订）》的通知.pdf | 缺少回答要点：岗位申请 |
| aid-combine-006 | 国家励志奖学金和国家奖学金是否可以兼得？ | 奖助学金 | partially_answerable | e8b2b9918594, 87cb45995557, 52a785d3df9c, 3e2ec161e017, 861408385e90 | 关于印发《上海财经大学本科生奖学金评选管理办法》的通知（上财行规[2025]22号）.pdf | 缺少回答要点：制度依据 |
| aid-assessment-007 | 综合测评如何计算？ | 奖助学金 | partially_answerable | 3e2ec161e017, 861408385e90, a7ba514b5aec, b880d66272a2, 1067b1ad3777 | 关于开展2024-2025学年国家励志奖学金评选工作的通知 | 缺少回答要点：评价项目 |
| aid-appeal-008 | 奖学金评选结果如何申诉？ | 奖助学金 | answerable | 1ab2328b6329, 4a24a8bbdf92, 3e2ec161e017, 861408385e90, 2e8a9386b4f8 | 关于开展2024年研究生国家奖学金评选工作的通知.pdf | — |
| aid-grant-009 | 本科生国家助学金如何申请？ | 奖助学金 | answerable | 145349451521, 4cb5fd791a1a, 87cb45995557, 3e2ec161e017, 861408385e90 | 关于开展2024-2025学年本科生国家助学金及社会助学金评选工作的通知.doc | — |
| aid-tuition-010 | 学费减免如何申请？ | 奖助学金 | answerable | 4cb5fd791a1a, b815e0eefe9a, 8f245c042322, c738554bdeee, 52a785d3df9c | 48f8b69e-45bb-4d19-91e9-6df752543a42.pdf | — |
| aid-campus-loan-011 | 校园地国家助学贷款如何办理？ | 奖助学金 | answerable | ee98c67e0dbc, 1f5aa08edc4d, 049a7db37997, 4256e93f19b3, 280b436e0a52 | 关于申请2022年中西部基层单位就业学费补偿国家助学贷款代偿的通知 | — |
| aid-origin-loan-012 | 生源地助学贷款如何办理学校确认？ | 奖助学金 | partially_answerable | ee98c67e0dbc, 52a785d3df9c, 045ddc88af3e, 5836ee860bf9, 204cdd70a17d | 关于申请2022年中西部基层单位就业学费补偿国家助学贷款代偿的通知 | 缺少回答要点：学校确认环节 |
| aid-military-aid-013 | 服兵役学生国家教育资助如何申请？ | 奖助学金 | answerable | 52a785d3df9c, 77ec547b2f2e, 145349451521, 1ab2328b6329, 0922e508be1d | bb74c415-f49b-4bb8-9f0b-3830b36fb8cc.pdf | — |
| aid-graduate-aid-014 | 研究生国家助学金的对象和发放规则是什么？ | 奖助学金 | partially_answerable | 0922e508be1d, 77ec547b2f2e, ad82461a66c4, 1ab2328b6329, 145349451521 | d993c56d-f948-45aa-8685-9bf99190224c.pdf | 缺少回答要点：制度依据 |
| aid-social-015 | 社会奖学金的评选条件和申请流程是什么？ | 奖助学金 | partially_answerable | 145349451521, 3cd9009d3563, 3e2ec161e017, 861408385e90, 2e8a9386b4f8 | 关于开展2024-2025学年本科生国家助学金及社会助学金评选工作的通知.doc | 缺少回答要点：年度通知 |
| admit-basic-001 | 推免基本条件是什么？ | 推免与招生 | partially_answerable | c5ae3d61e34e, caef95227715, 83b8da8365ee, 36481bbba58c, 739c8bdca878 | 上海财经大学推荐优秀应届本科毕业生免试攻读研究生工作管理办法（试行）.pdf | 缺少回答要点：制度依据 |
| admit-college-002 | 学院推免自定条件是什么？ | 推免与招生 | partially_answerable | f900e2c94b7f, 397ea76bef2e, 377bbc3c92b9, abd84963c34a, 75c5c197f4f5 | 关于上海财经大学2027年接收优秀应届本科毕业生免试攻读研究生（含直博生）预报名的通知 | 缺少回答要点：学院实施细则 |
| admit-fail-003 | 推免申请是否要求没有挂科记录？ | 推免与招生 | partially_answerable | c5ae3d61e34e, 2675703133ac, 36481bbba58c, 1fb82cab054b, 1c38828bd054 | 上海财经大学推荐优秀应届本科毕业生免试攻读研究生工作管理办法（试行）.pdf | 缺少回答要点：适用年级; 缺少回答要点：制度依据 |
| admit-ranking-004 | 推免综合成绩排名如何确定？ | 推免与招生 | partially_answerable | e6d269205cb4, 2675703133ac, c5ae3d61e34e, 3db4ae2f926a, 12d8bae93ae8 | 上海财经大学会计学院关于举办“第十一届全国优秀大学生夏令营”的通知 | 缺少回答要点：成绩组成 |
| admit-materials-005 | 推免申请需要提交哪些材料？ | 推免与招生 | answerable | c5ae3d61e34e, f900e2c94b7f, 397ea76bef2e, 377bbc3c92b9, abd84963c34a | 上海财经大学推荐优秀应届本科毕业生免试攻读研究生工作管理办法（试行）.pdf | — |
| admit-process-006 | 学校推免生推荐流程是什么？ | 推免与招生 | partially_answerable | e6d269205cb4, f900e2c94b7f, ec97cb99d0b2, 397ea76bef2e, 377bbc3c92b9 | 上海财经大学会计学院关于举办“第十一届全国优秀大学生夏令营”的通知 | 缺少回答要点：学校遴选; 缺少回答要点：公示环节 |
| admit-backup-007 | 推免候补资格如何确定？ | 推免与招生 | answerable | ec97cb99d0b2, 377bbc3c92b9, 75c5c197f4f5, 453839cda7a3, e6d269205cb4 | 关于确定我校2026年推荐优秀应届本科毕业生免试攻读研究生名单的公告 | — |
| admit-direct-phd-008 | 本科直博生如何申请？ | 推免与招生 | answerable | e6d269205cb4, 36481bbba58c, f900e2c94b7f, 397ea76bef2e, 377bbc3c92b9 | 上海财经大学会计学院关于举办“第十一届全国优秀大学生夏令营”的通知 | — |
| admit-preapply-009 | 本科生申请免试攻读研究生预报名如何办理？ | 推免与招生 | partially_answerable | 377bbc3c92b9, f900e2c94b7f, 397ea76bef2e, abd84963c34a, 75c5c197f4f5 | 上海财经大学2025年接收推荐免试研究生（含直博生）预报名通知 | 缺少回答要点：适用对象 |
| admit-phd-assess-010 | 博士申请考核制招生如何报名？ | 推免与招生 | answerable | c0c2a73030c1, abd84963c34a, 354be832f02e, 5d4628bc8faa, b50750ea2d92 | 上海财经大学2026年少数民族高层次骨干人才计划研究生招生办法 | — |
| admit-master-book-011 | 硕士研究生招生简章在哪里查询？ | 推免与招生 | answerable | 2675703133ac, 12d8bae93ae8, 844338d7d8e8, a195015394f5, c0c2a73030c1 | 上海财经大学2020年招收攻读硕士学位研究生初试成绩公布后相关问题汇总（一） | — |
| admit-doctor-book-012 | 博士研究生招生简章和招生规定在哪里查询？ | 推免与招生 | answerable | c0c2a73030c1, 2675703133ac, a195015394f5, 12d8bae93ae8, 844338d7d8e8 | 上海财经大学2026年少数民族高层次骨干人才计划研究生招生办法 | — |
| admit-subject-013 | 研究生招生考试科目调整公告如何查询？ | 推免与招生 | partially_answerable | 12d8bae93ae8, 844338d7d8e8, 2675703133ac, f1ea04ce7270, 1c2f52326aef | 上海财经大学2026年招收攻读硕士学位研究生初试成绩公布后相关问题汇总 | 缺少回答要点：适用专业; 缺少回答要点：调整内容; 缺少回答要点：生效年度 |
| admit-public-014 | 推免和研究生招生公示名单在哪里查询？ | 推免与招生 | partially_answerable | c5ae3d61e34e, e364a11babc8, a71e462969f2, eba4c01caadd, 2675703133ac | 上海财经大学推荐优秀应届本科毕业生免试攻读研究生工作管理办法（试行）.pdf | 缺少回答要点：公示栏目; 缺少回答要点：名单类型 |
| admit-adjust-015 | 硕士研究生调剂和复试办法如何查询？ | 推免与招生 | partially_answerable | 835e0c88d087, efa51818dbb9, 2675703133ac, a195015394f5, 12d8bae93ae8 | 上海财经大学2024年硕士研究生招生复试录取办法 | 缺少回答要点：适用对象 |
| career-recommend-001 | 就业推荐表如何制作？ | 就业手续 | answerable | b2ada26c2482, 8148b7313c10, 91d57e91aa8d, 1ddf06568d3f, 964187cd9859 | 附件4+报考指南.doc | — |
| career-paper-tripartite-002 | 纸质三方协议如何办理？ | 就业手续 | answerable | 91d57e91aa8d, 1ddf06568d3f, 964187cd9859, 995be6076c48, 41c92321e929 | 附件1-江西省2026年度选调应届优秀大学毕业生报考须知.pdf | — |
| career-online-sign-003 | 网签流程是什么？ | 就业手续 | partially_answerable | b2ada26c2482, 91d57e91aa8d, 1ddf06568d3f, 48cefabc4b23, 964187cd9859 | 附件4+报考指南.doc | 缺少回答要点：生效确认 |
| career-terminate-004 | 三方协议填错或解约怎么办？ | 就业手续 | partially_answerable | 91d57e91aa8d, 964187cd9859, 995be6076c48, 1d7b01c703dc, 605f9d352c40 | 附件1-江西省2026年度选调应届优秀大学毕业生报考须知.pdf | 缺少回答要点：适用情形 |
| career-destination-005 | 毕业去向如何登记？ | 就业手续 | partially_answerable | b2ada26c2482, a35bd57d017e, 48cefabc4b23, b71587be94bc, 2ad299b0b4b2 | 附件4+报考指南.doc | 缺少回答要点：去向类型 |
| career-archive-006 | 毕业档案如何查询？ | 就业手续 | partially_answerable | b2ada26c2482, 1ddf06568d3f, 48cefabc4b23, 41c92321e929, 91d57e91aa8d | 附件4+报考指南.doc | 缺少回答要点：档案去向 |
| career-shanghai-007 | 非上海生源申请上海户籍需要哪些材料？ | 就业手续 | answerable | 91d57e91aa8d, a35bd57d017e, 28cf1ba96325, 81b1305a9135, b2ada26c2482 | 附件1-江西省2026年度选调应届优秀大学毕业生报考须知.pdf | — |
| career-graduate-008 | 考上研究生后已签三方怎么办？ | 就业手续 | partially_answerable | 91d57e91aa8d, 28cf1ba96325, 1ddf06568d3f, 964187cd9859, 995be6076c48 | 附件1-江西省2026年度选调应届优秀大学毕业生报考须知.pdf | 缺少回答要点：适用情形; 缺少回答要点：去向变更 |
| career-unemployed-009 | 不就业登记如何办理？ | 就业手续 | answerable | b2ada26c2482, 91d57e91aa8d, 8148b7313c10, 8439b4f46be6, 5195ab519575 | 附件4+报考指南.doc | — |
| career-flexible-010 | 灵活就业如何登记？ | 就业手续 | answerable | b2ada26c2482, 91d57e91aa8d, 1d7b01c703dc, 605f9d352c40, e1ab689096c9 | 附件4+报考指南.doc | — |
| career-grassroots-011 | 基层就业项目需要办理哪些就业手续？ | 就业手续 | partially_answerable | 1ddf06568d3f, 964187cd9859, 995be6076c48, becc8e1e9607, ec7966496f4a | 河北省2026年度定向选调生招录公告 | 缺少回答要点：政策依据 |
| career-military-012 | 征兵就业政策和就业去向如何登记？ | 就业手续 | answerable | b2ada26c2482, 8439b4f46be6, 964187cd9859, 995be6076c48, 91d57e91aa8d | 附件4+报考指南.doc | — |
| career-change-013 | 毕业生就业去向登记后如何变更？ | 就业手续 | answerable | b2ada26c2482, b71587be94bc, 1d7b01c703dc, 605f9d352c40, e1ab689096c9 | 附件4+报考指南.doc | — |
| career-agency-014 | 签约单位变更时就业手续如何办理？ | 就业手续 | partially_answerable | 91d57e91aa8d, 7a12ae4c3893, 973fb5ea32f5, 1ddf06568d3f, 8148b7313c10 | 附件1-江西省2026年度选调应届优秀大学毕业生报考须知.pdf | 缺少回答要点：适用情形 |
| career-manual-015 | 就业系统学生操作手册在哪里下载？ | 就业手续 | partially_answerable | 1ddf06568d3f, b2ada26c2482, 7a12ae4c3893, becc8e1e9607, ec7966496f4a | 河北省2026年度定向选调生招录公告 | 缺少回答要点：技术支持 |
| housing-holiday-001 | 寒暑假如何申请留校住宿？ | 宿舍后勤 | partially_answerable | fc4db938e9a8, a52286f6863a, eed57bcd7dd7, cd2f0a2c4d74, 4142746d68d4 | 大学生医保问答及相关管理办法 | 缺少回答要点：申请对象 |
| housing-checkout-002 | 如何办理退宿？ | 宿舍后勤 | answerable | a52286f6863a, fc4db938e9a8, cd2f0a2c4d74, eed57bcd7dd7, 4142746d68d4 | 上海财经大学“爱心小屋”临时住宿协议.doc | — |
| housing-deferred-003 | 延期毕业还能住宿吗？ | 宿舍后勤 | partially_answerable | cd2f0a2c4d74, a52286f6863a, c2153b7c8e03, fc4db938e9a8, 4142746d68d4 | 学生宿舍日常办事指南 | 缺少回答要点：适用对象 |
| housing-adjust-004 | 宿舍调整需要什么流程？ | 宿舍后勤 | answerable | fc4db938e9a8, cd2f0a2c4d74, 4142746d68d4, a52286f6863a, c2153b7c8e03 | 大学生医保问答及相关管理办法 | — |
| housing-apply-005 | 新生或在校生住宿申请在哪里办理？ | 宿舍后勤 | partially_answerable | fc4db938e9a8, cd2f0a2c4d74, eed57bcd7dd7, a52286f6863a, 37bece6a4ca6 | 大学生医保问答及相关管理办法 | 缺少回答要点：对象 |
| housing-repair-006 | 宿舍如何报修？ | 宿舍后勤 | answerable | 4142746d68d4, a52286f6863a, c2153b7c8e03, fc4db938e9a8, cd2f0a2c4d74 | 上海财经大学学生园区“爱心小屋”使用申请表.doc | — |
| housing-electric-007 | 宿舍内可以使用哪些电器？ | 宿舍后勤 | partially_answerable | a52286f6863a, fc4db938e9a8, cd2f0a2c4d74, 4142746d68d4, c2153b7c8e03 | 上海财经大学“爱心小屋”临时住宿协议.doc | 缺少回答要点：允许电器; 缺少回答要点：禁用电器; 缺少回答要点：管理依据 |
| housing-temporary-008 | 临时住宿如何申请？ | 宿舍后勤 | partially_answerable | a52286f6863a, fc4db938e9a8, cd2f0a2c4d74, 4142746d68d4, eed57bcd7dd7 | 上海财经大学“爱心小屋”临时住宿协议.doc | 缺少回答要点：适用对象 |
| housing-catering-009 | 学校餐饮服务和就餐问题应联系哪里？ | 宿舍后勤 | answerable | fc4db938e9a8, a52286f6863a, 9525c214a5a9, cd2f0a2c4d74, 480760984ceb | 大学生医保问答及相关管理办法 | — |
| housing-express-010 | 校园快递服务在哪里查询或反馈？ | 宿舍后勤 | answerable | fc4db938e9a8, 480760984ceb, 9525c214a5a9, a52286f6863a, cd2f0a2c4d74 | 大学生医保问答及相关管理办法 | — |
| nic-activate-001 | 统一认证账号如何激活？ | 信息化与校园卡 | partially_answerable | 9e36c2f95bfe, fd893261ff29, f4504c68982d, 077ec1d6692d, 40484c99851e | 统一认证 | 缺少回答要点：身份验证; 缺少回答要点：技术支持 |
| nic-password-002 | 统一认证密码忘了怎么办？ | 信息化与校园卡 | answerable | fd893261ff29, 9e36c2f95bfe, f4504c68982d, 077ec1d6692d, 5047ad905af6 | 一、校园一卡通简介 | — |
| nic-freeze-003 | 统一认证账号为什么被冻结？ | 信息化与校园卡 | partially_answerable | 9e36c2f95bfe, fd893261ff29, 5047ad905af6, f4504c68982d, 077ec1d6692d | 统一认证 | 缺少回答要点：冻结原因 |
| nic-arrears-004 | 欠费后账号如何解冻？ | 信息化与校园卡 | answerable | 9e36c2f95bfe, fd893261ff29, 5047ad905af6, 7dcfaeceef5f, a648ee0a55f3 | 统一认证 | — |
| nic-card-005 | 校园卡如何充值和挂失？ | 信息化与校园卡 | answerable | fd893261ff29, 9e36c2f95bfe, 077ec1d6692d, 7dcfaeceef5f, a648ee0a55f3 | 一、校园一卡通简介 | — |
| nic-ecard-006 | 电子校园卡如何领取？ | 信息化与校园卡 | partially_answerable | fd893261ff29, 077ec1d6692d, 9e36c2f95bfe, f4504c68982d, 40484c99851e | 一、校园一卡通简介 | 缺少回答要点：故障处理 |
| nic-wifi-007 | 如何连接校园无线网？ | 信息化与校园卡 | partially_answerable | 7dcfaeceef5f, a648ee0a55f3, 5047ad905af6, 3a12c66406ab, 077ec1d6692d | 无线联网 | 缺少回答要点：网络名称; 缺少回答要点：适用终端; 缺少回答要点：故障排查 |
| nic-wired-008 | 校园有线网络如何开通？ | 信息化与校园卡 | partially_answerable | 7dcfaeceef5f, a648ee0a55f3, 3a12c66406ab, fd893261ff29, 077ec1d6692d | 无线联网 | 缺少回答要点：技术支持 |
| nic-eduroam-009 | 如何使用 Eduroam？ | 信息化与校园卡 | partially_answerable | 5047ad905af6, 434f98ee0dd5, 9e36c2f95bfe, fd893261ff29, f4504c68982d | Eduroam | 缺少回答要点：适用对象 |
| nic-email-010 | 毕业后学校邮箱和统一认证还能使用多久？ | 信息化与校园卡 | partially_answerable | 51addf1ea6fd, 9e36c2f95bfe, fd893261ff29, 077ec1d6692d, 434f98ee0dd5 | 电子邮箱 | 缺少回答要点：适用对象; 缺少回答要点：账号状态 |
| nic-vpn-011 | VPN 如何使用？ | 信息化与校园卡 | partially_answerable | 019689e79ce5, 077ec1d6692d, 34d558436042, 40484c99851e, 434f98ee0dd5 | MacOS系统VPN客户端MotionPro_Plus设置说明.pdf | 缺少回答要点：适用资源 |
| nic-wechat-012 | 企业微信如何绑定学校身份？ | 信息化与校园卡 | partially_answerable | fd893261ff29, 5047ad905af6, 49fb73e02893, f4504c68982d, 34d558436042 | 一、校园一卡通简介 | 缺少回答要点：技术支持 |
| nic-one-stop-013 | 一网通办如何进入学生服务？ | 信息化与校园卡 | partially_answerable | 34d558436042, fd893261ff29, 077ec1d6692d, 9e36c2f95bfe, f4504c68982d | 一网通办 | 缺少回答要点：服务查找 |
| nic-teaching-014 | 上财教学网的登录和访问方式是什么？ | 信息化与校园卡 | partially_answerable | 077ec1d6692d, 019689e79ce5, 9e36c2f95bfe, 40484c99851e, 5047ad905af6 | 上财教学网 | 缺少回答要点：适用对象; 缺少回答要点：技术支持 |
| nic-supercomputer-015 | 学生如何申请使用超算平台？ | 信息化与校园卡 | partially_answerable | fd893261ff29, 434f98ee0dd5, 077ec1d6692d, f4504c68982d, 34d558436042 | 一、校园一卡通简介 | 缺少回答要点：账号申请 |
| library-hours-001 | 图书馆开放时间是什么？ | 图书馆 | partially_answerable | eb36ca9f5d3f, 59b3b5517051, fb45c29d5189, ffb9750af1bf, f77bfc37b926 | 续借及预约 | 缺少回答要点：开放校区 |
| library-permission-002 | 本科生是否自动开通借阅权限？ | 图书馆 | answerable | eb36ca9f5d3f, 59b3b5517051, f77bfc37b926, fb45c29d5189, c172696f9d84 | 续借及预约 | — |
| library-loan-003 | 图书可以借多久？ | 图书馆 | partially_answerable | 59b3b5517051, eb36ca9f5d3f, f77bfc37b926, 10cc83bd33cd, fb45c29d5189 | 馆际互借 | 缺少回答要点：逾期处理 |
| library-renew-004 | 如何续借或预约图书？ | 图书馆 | answerable | eb36ca9f5d3f, 59b3b5517051, f77bfc37b926, fb45c29d5189, ffb9750af1bf | 续借及预约 | — |
| library-overdue-005 | 图书逾期如何处理？ | 图书馆 | answerable | eb36ca9f5d3f, fb45c29d5189, 59b3b5517051, f77bfc37b926, 10cc83bd33cd | 续借及预约 | — |
| library-offcampus-006 | 校外如何访问图书馆数据库？ | 图书馆 | partially_answerable | 10cc83bd33cd, c172696f9d84, e53f5dc2d698, ffb9750af1bf, f77bfc37b926 | 校外访问 | 缺少回答要点：技术支持 |
| library-seat-007 | 如何预约图书馆座位？ | 图书馆 | partially_answerable | eb36ca9f5d3f, 59b3b5517051, f77bfc37b926, fb45c29d5189, ffb9750af1bf | 续借及预约 | 缺少回答要点：违约处理 |
| library-room-008 | 如何预约图书馆研讨室？ | 图书馆 | answerable | eb36ca9f5d3f, 10cc83bd33cd, 59b3b5517051, f77bfc37b926, fb45c29d5189 | 续借及预约 | — |
| library-ill-009 | 如何申请馆际互借或文献传递？ | 图书馆 | answerable | 59b3b5517051, f77bfc37b926, 10cc83bd33cd, e53f5dc2d698, eb36ca9f5d3f | 馆际互借 | — |
| library-print-010 | 图书馆自助打印在哪里办理？ | 图书馆 | answerable | 59b3b5517051, c172696f9d84, eb36ca9f5d3f, fb45c29d5189, f77bfc37b926 | 馆际互借 | — |
| medical-insurance-001 | 大学生医保如何使用？ | 医疗医保 | answerable | ad5c41a94918, 28429d197c37, 9e5d6d9c3bfb, 65b1c0021b0d, 66e45969c386 | 关于2025级新生申报2025年后半年大学生城乡居民基本医保（免缴费）的通知 | — |
| medical-outpatient-002 | 大学生医保门诊如何报销？ | 医疗医保 | answerable | 65b1c0021b0d, 66e45969c386, a82ebc6cabb7, 28429d197c37, 9e5d6d9c3bfb | 本市大学生持卡就医结算后的一些常见问题 | — |
| medical-referral-003 | 校外就医是否需要转诊？ | 医疗医保 | partially_answerable | a82ebc6cabb7, 28429d197c37, 9e5d6d9c3bfb, bd003ceb1949, e932c31dd548 | 大学生医疗保障及就医服务相关问题解答 | 缺少回答要点：适用医院 |
| medical-hospital-004 | 住院如何办理结算？ | 医疗医保 | answerable | 28429d197c37, 9e5d6d9c3bfb, 65b1c0021b0d, 66e45969c386, bd003ceb1949 | 关于居民医保就医结算操作介绍 （大学生2024年11月版） | — |
| medical-excluded-005 | 哪些医疗费用不能报销？ | 医疗医保 | partially_answerable | 28429d197c37, 9e5d6d9c3bfb, 65b1c0021b0d, 66e45969c386, bd003ceb1949 | 关于居民医保就医结算操作介绍 （大学生2024年11月版） | 缺少回答要点：适用政策 |
| medical-location-006 | 校医院在哪里，如何联系？ | 医疗医保 | answerable | 157e8ee4461b, e932c31dd548, a82ebc6cabb7, e0674f67c4bd, f27b1443e10a | 2024秋季开学校园传染性疾病宣教及处置流程 | — |
| medical-offsite-007 | 异地就医如何办理备案或报销？ | 医疗医保 | partially_answerable | 28429d197c37, 9e5d6d9c3bfb, 65b1c0021b0d, 66e45969c386, bd003ceb1949 | 关于居民医保就医结算操作介绍 （大学生2024年11月版） | 缺少回答要点：适用对象 |
| medical-physical-008 | 学生体检在哪里预约或办理？ | 医疗医保 | answerable | afe3e95bb50a, 55d2fac9dad1, 28429d197c37, 9e5d6d9c3bfb, bd003ceb1949 | 上海财经大学学生医疗保障制度实施细则 | — |
| medical-infectious-009 | 学校传染病管理和报告流程是什么？ | 医疗医保 | answerable | 157e8ee4461b, 65b1c0021b0d, 66e45969c386, bd003ceb1949, 28429d197c37 | 2024秋季开学校园传染性疾病宣教及处置流程 | — |
| medical-download-010 | 医疗医保常用表格在哪里下载？ | 医疗医保 | partially_answerable | 28429d197c37, 9e5d6d9c3bfb, 65b1c0021b0d, 66e45969c386, bd003ceb1949 | 关于居民医保就医结算操作介绍 （大学生2024年11月版） | 缺少回答要点：适用事项 |
| exchange-program-001 | 学生交换项目在哪里查询？ | 国际交流 | answerable | 7d86bdf70ff8, 440e560398ab, c688036c17e7, bdd807dfb79a, 2675703133ac | 2026年学生境外学习项目概览 | — |
| exchange-condition-002 | 交换项目申请条件是什么？ | 国际交流 | answerable | c688036c17e7, 440e560398ab, f511bc1fc4a2, 7d86bdf70ff8, f8015ab6e16f | Q&A | 2026-2027学年海外交流学习常见问题答疑 | — |
| exchange-materials-003 | 交换项目报名需要哪些材料？ | 国际交流 | answerable | 440e560398ab, c688036c17e7, bdd807dfb79a, f900e2c94b7f, 397ea76bef2e | Q&A | 境外学习常见问题解答 | — |
| exchange-selection-004 | 交换项目选拔流程是什么？ | 国际交流 | partially_answerable | 440e560398ab, bdd807dfb79a, c688036c17e7, 7d86bdf70ff8, a50221cc7070 | Q&A | 境外学习常见问题解答 | 缺少回答要点：面试或考核; 缺少回答要点：结果公示 |
| exchange-funding-005 | 学生交流项目有哪些资助？ | 国际交流 | answerable | a50221cc7070, f511bc1fc4a2, f8015ab6e16f, 220adadfc5cc, 0ee8ebbdf902 | 上海财经大学关于2022年国家建设高水平大学公派研究生项目选拔及申请受理工作的安排 | — |
| exchange-predeparture-006 | 出国交流行前手续如何办理？ | 国际交流 | answerable | c688036c17e7, 440e560398ab, f511bc1fc4a2, f8015ab6e16f, 220adadfc5cc | Q&A | 2026-2027学年海外交流学习常见问题答疑 | — |
| exchange-credit-007 | 海外交流成绩和学分如何认定？ | 国际交流 | answerable | c688036c17e7, 440e560398ab, e6d269205cb4, 60f9a164fe20, f900e2c94b7f | Q&A | 2026-2027学年海外交流学习常见问题答疑 | — |
| exchange-short-008 | 短期国际交流如何申请？ | 国际交流 | answerable | 440e560398ab, f511bc1fc4a2, c688036c17e7, f8015ab6e16f, 220adadfc5cc | Q&A | 境外学习常见问题解答 | — |
| exchange-public-009 | 公派留学项目如何报名？ | 国际交流 | partially_answerable | a50221cc7070, f511bc1fc4a2, 94b61196bf6e, 440e560398ab, 93d28201f44b | 上海财经大学关于2022年国家建设高水平大学公派研究生项目选拔及申请受理工作的安排 | 缺少回答要点：资助政策 |
| exchange-contact-010 | 国际交流项目的咨询联系方式是什么？ | 国际交流 | answerable | c688036c17e7, 440e560398ab, f8015ab6e16f, 220adadfc5cc, 0ee8ebbdf902 | Q&A | 2026-2027学年海外交流学习常见问题答疑 | — |
| new-report-001 | 新生入学报到需要办理哪些手续？ | 新生与安全 | answerable | 52a785d3df9c, 5220cf43e76b, 2fe0ae1e3ab7, 4cb5fd791a1a, b815e0eefe9a | bb74c415-f49b-4bb8-9f0b-3830b36fb8cc.pdf | — |
| new-orientation-002 | 新生如何领取校园卡并开通相关服务？ | 新生与安全 | answerable | 5220cf43e76b, 52a785d3df9c, 418fee24b2e9, 480760984ceb, a6a7b44dd541 | 9903a61e-8740-4c78-809d-fe160d8ddad5.pdf | — |
| new-household-003 | 户籍和学籍证明如何办理？ | 新生与安全 | answerable | 52a785d3df9c, 1f5aa08edc4d, 2fe0ae1e3ab7, 5220cf43e76b, eed57bcd7dd7 | bb74c415-f49b-4bb8-9f0b-3830b36fb8cc.pdf | — |
| new-military-registration-004 | 大学生兵役登记如何办理？ | 新生与安全 | answerable | 2fe0ae1e3ab7, 52a785d3df9c, 5c8241801dd8, 7f8293cb80ec, 0922e508be1d | 上海财经大学2016年征兵工作通知 | — |
| new-enlistment-005 | 在校生参军入伍流程是什么？ | 新生与安全 | answerable | 2fe0ae1e3ab7, 52a785d3df9c, 2e8a9386b4f8, 57d4620aea1b, 8f245c042322 | 上海财经大学2016年征兵工作通知 | — |
| new-traffic-006 | 校园交通和车辆管理有哪些规定？ | 新生与安全 | answerable | 52a785d3df9c, 2fe0ae1e3ab7, 9525c214a5a9, 4cb5fd791a1a, 5220cf43e76b | bb74c415-f49b-4bb8-9f0b-3830b36fb8cc.pdf | — |
| new-lost-007 | 校园失物招领如何办理？ | 新生与安全 | answerable | 5220cf43e76b, 52a785d3df9c, 1f5aa08edc4d, 2fe0ae1e3ab7, ee98c67e0dbc | 9903a61e-8740-4c78-809d-fe160d8ddad5.pdf | — |
| new-safety-008 | 校园安全事件应如何报告和求助？ | 新生与安全 | answerable | 1f5aa08edc4d, 418fee24b2e9, 5220cf43e76b, 52a785d3df9c, 2fe0ae1e3ab7 | 关于印发《上海财经大学学生违纪处分规定（2023年10月修订）》的通知.pdf | — |
| new-fraud-009 | 校园电信网络诈骗如何举报和求助？ | 新生与安全 | partially_answerable | 1f5aa08edc4d, 418fee24b2e9, 5220cf43e76b, 52a785d3df9c, 13fe448b5b0b | 关于印发《上海财经大学学生违纪处分规定（2023年10月修订）》的通知.pdf | 缺少回答要点：识别提示; 缺少回答要点：紧急措施 |
| new-download-010 | 保卫处常用证明和表格在哪里下载？ | 新生与安全 | partially_answerable | 1be2da8f5d92, b5e1c6ef7ecd, 16392d954e77, eed57bcd7dd7, 1f5aa08edc4d | 集体宿舍证明.docx | 缺少回答要点：适用事项 |
