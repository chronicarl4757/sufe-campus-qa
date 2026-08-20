# Exam_2021_solutions.pdf

所属通知：上海财经大学2024年交叉科学实验班报名表及往期试题
发布日期：2024-08-11
发布单位：上海财经大学信息管理与工程学院
原发布页：https://sime.sufe.edu.cn/1c/23/c10226a203811/page.htm
附件下载地址：https://sime.sufe.edu.cn/_upload/article/files/e2/1a/bcae6def4bf2bebb93ebff6806f1/eeb46ca7-917c-4631-91f0-0dfe3c716a83.pdf

## 附件正文

Shanghai University of Finance and Economics
Entrance Examination for 2021 Interdisciplinary Sciences Elite Program
Date: September 03, 2021
Time: 6:00pm – 10:00pm
Background
“Mystery boxes” (盲盒) are gaining great popularity in China in recent years. A
mystery box is a special product that contains random goods (随机商品) in it. The
buyer does not know what is inside the box at the time of purchase. Such a product is
often called a probabilistic good (概率商品).
A probabilistic good oﬀers a probability of getting any one of a set of items. We use
probabilistic selling (概率销售) to denote (表示) the selling strategy (销售策略) under
which the seller creates probabilistic goods using the seller’s existing products or services
and oﬀers such probabilistic goods to potential buyers as additional purchase choices.
For example, a retailer selling two diﬀerent colors of sweaters, red and green, may oﬀer
an additional “probabilistic sweater,” which can be either the red or green sweater. We
use the term traditional selling (传统销售) to denote the conventional selling strategy
under which the seller only oﬀers the existing goods (i.e., no probabilistic good) for sale.
Our interest is to compare the two selling strategies and explore the fundamental
product/market conditions required for the beneﬁt of introducing uncertainty in product
assignments by oﬀering “probabilistic goods”.
Traditional Selling Strategy
We start with the analysis of the traditional selling strategy. Consider a ﬁrm oﬀering
two component goods, j = 1, 2, which have the same production costs (生产成本): c1 =
c2 = c, 0 < c < 1. We assume that the seller is aware of the demand (需求) and able to
satisfy all demand (if it so desires). Under the traditional selling strategy, the ﬁrm sells
each good j at a price pj. We assume that 0 ≤pj ≤1 for j = 1, 2. The ﬁrm’s objective
is to determine the prices of the goods to maximize (最大化) its total proﬁt (利润).
Let vji be the value of good j to consumer (消费者) i. Diﬀerent consumers have
diﬀerent tastes. Some may like good 1 more than good 2, but others may like good 2
more. To describe consumers’ diﬀerent tastes, we assume all consumers are uniformly
1
(均匀地) located on the interval (区间) [0,1], good 1 is located at point 0, and good 2
is located at point 1 (see Figure 1). A consumer likes a good more if she is closer to
this good. Let xi denote consumer i’s location. The valuations (评分值) of two goods to
consumer i are



v1i = 1 −xi,
v2i = xi,
where xi ∈[0, 1].
(1)
For example, as shown in Figure 1, if consumer i’s location in the interval is 1/2, i.e.,
xi = 1/2, then her valuation for both good 1 and good 2 are 1/2. If her location is at
1/4, i.e., xi = 1/4, then her valuation for good 1 and good 2 are respectively (分别是)
3/4 and 1/4. In this case, because the consumer is located closer to good 1, her valuation
for good 1 is higher.
!
"
!""#$%
!""#$&
!! " #$%
图1: Consumer valuation
We assume each consumer buys at most one good. The consumer’s utility (效用值)
from buying a good is the diﬀerence between her valuation and the price of this good. For
example, the utility of consumer i from buying good 1 (or good 2) under the traditional
selling strategy is v1i −p1 (or v2i −p2).
Under the traditional selling strategy, each consumer has three choices: (a) buy good
1, (b) buy good 2, and (c) buy nothing. She chooses the one that leads to the highest
utility. More speciﬁcally, consumer i will buy good 1 if
v1i −p1 ≥v2i −p2 and v1i −p1 ≥0;
and she will buy nothing if
v1i −p1 < 0 and v2i −p2 < 0.
Next, we derive (推导) the demand function (需求函数) which shows the relationship
between the prices of two goods and the sizes of consumers buying the goods at those
prices. Recall that consumers are uniformly located in interval [0,1]. Because the shorter
is the distance between a consumer and a good, the higher is the valuation of the consumer
from buying this good, given the prices of two goods, consumers will be divided into at
2
most three segments (区间的分割) as shown in Figure 2. In particular, consumers in the
left segment [0,ˆx1] buy good 1, consumers in the right segment [ˆx2,1] buy good 2, and
consumers in the middle segment (ˆx1, ˆx2) buy nothing.
Let D1(p1, p2) represent the demand function for good 1 under the traditional selling
strategy (D1(p1, p2)是一个自变量为p1, p2的二元函数). It is the length of segment [0, ˆx1]
(as you know, this is simply ˆx1). Let D2(p1, p2) represent the demand function for good
2, which is the length of segment [ˆx2, 1] (this is simply 1 −ˆx2). Therefore, to determine
D1(p1, p2) and D2(p1, p2), we need to ﬁgure out the thresholds (分界点) ˆx1 and ˆx2.
Question 1 (15 pts): Show that, under the traditional selling strategy, the demand for
good 1 is given by
D1(p1, p2) =



1 −p1
if p1 + p2 ≥1,
1 −p1 + p2
2
if p1 + p2 < 1.
(Hint: for the consumer at location ˆx1, she should be indiﬀerent (无区别的) between
buying good 1 and not buying good 1, i.e., buying good 2 or buying nothing. Mathemat-
ically, this is equivalent to 1 −ˆx1 −p1 = max{0, ˆx1 −p2}. You can consider two cases:
(1) 1 −ˆx1 −p1 = 0 ≥ˆx1 −p2, (2) 1 −ˆx1 −p1 = ˆx1 −p2 > 0. Note that ˆx1 is within the
interval [0,1].)
!
"
!""#$%
!""#$&
!"&
!"'
'()$*""# %
'()$*""# &
图2: Consumer segments
Answer 1: In case (1) we get from 1 −ˆx1 −p1 = 0 that ˆx1 = 1 −p1. Then, from
ˆx1 −p2 ≤0 we further get p1 + p2 ≥1. In case (2), we get from 1 −ˆx1 −p1 = ˆx1 −p2
that ˆx1 = (1 −p1 + p2)/2. Then from ˆx1 −p2 ≥0 we get p1 + p2 < 1. The demand for
good 1 is the length of the segment [0, ˆx]1, so D1(p1, p2) = ˆx1.
Let F(p1, p2) denote the proﬁt function of the ﬁrm. Next, we determine the optimal
(最优的) prices that maximize F(p1, p2), which is given by
F(p1, p2) =
2
X
j=1
(pj −c) · Dj(p1, p2)
(2)
3
Assume good 2 has the same demand as good 1, D2(p1, p2) = D1(p1, p2).
Here
D1(p1, p2) is the expression (表达式) in Question 1. Also assume the seller always set the
same price for the two goods p1 = p2 = p. Then we can rewrite the two demand functions
as ¯D(p) = D1(p, p) and the proﬁt function as ¯F(p) = F(p, p).
Question 2 (15 pts): Write down the demand function ¯D(p) and the proﬁt function
¯F(p). Find the optimal price p∗(that is, the value of p (p的取值) that maximizes ¯F(p))
and the corresponding (相应的) optimal proﬁt F ∗= ¯F(p∗).
Answer 2: When p1 = p2 = p, we know that
¯D(p) = D1(p, p) =



1 −p
if p ≥1/2,
1/2
if p < 1/2.
Then we can get
¯F(p) = 2(p −c) ¯D(p) =



2(p −c)(1 −p)
if p ≥1/2,
p −c
if p < 1/2.
When p ≥1/2, the optimal price is (1 + c)/2 (which is guaranteed to be > 1/2 since
c > 0), and the optimal proﬁt is (1 −c)2/2. When p < 1/2, the optimal price is 1/2,
and optimal proﬁt is 1
2 −c). Clearly (1 −c)2/2 > 1
2 −c, so the ﬁnal optimal price is
p∗= (1 + c)/2, and optimal proﬁt is F ∗= (1 −c)2/2.
Probabilistic Selling Strategy
Next, we study the probabilistic selling strategy. In this case, the ﬁrm sells each
component good j at a price qj (j = 1, 2). The ﬁrm also sells at price q0 a probabilistic
good, which has probability 1/2 to be component good 1 and probability 1/2 to be
component good 2. We assume that 0 ≤qj ≤1 for j = 0, 1, 2.
Suppose consumer i’s valuation for the probabilistic good is
v0i = 1
2v1i + 1
2v2i,
her utility from buying good 1 (or good 2) is v1i −q1 (or v2i −q2), and her utility from
buying the probabilistic good is v0i −q0.
Under the probabilistic selling strategy, consumer i has four choices: (a) buy product
1, (b) buy product 2, (c) buy the probabilistic good, and (d) buy nothing. She chooses
the one that has the highest utility. For example, consumer i will buy product 1 if
v1i −q1 ≥v2i −q2 and v1i −q1 ≥v0i −q0 and v1i −q1 ≥0;
4
and she will buy nothing if
v1i −q1 < 0 and v2i −q2 < 0 and v0i −q0 < 0.
To simplify the analysis, we assume that the ﬁrm always sets the same price for good
1 and good 2, that is, q1 = q2 = q.
Question 3 (15 pts): Prove that, if q0 > q, then nobody will buy the probabilistic
good. (Hint: Analyze the valuation of a consumer from buying the probabilistic good
and compare it with the valuation from buying either good 1 or good 2.)
Answer 3: When q0 > q, we have
1
2(1 −xi) + 1
2xi −q0 < 1
2(1 −xi −q) + 1
2(xi −q)
for any xi ∈[0, 1]. That is, the utility of probabilistic good is less than the average of
the utilities of the two component goods. Therefore, utility of probabilistic good has to
be less than either one of the utilities of the two component goods
From Question 3, we know that if the seller decides to oﬀer the probabilistic good,
she must set q0 ≤q.
If q0 ≤q, consumers located close to
1
2 are likely to buy the
probabilistic good. Thus consumers will be divided into at most ﬁve segments as shown
in Figure 3. In particular, consumers in the left segment [0,ˆx1] buy good 1, consumers in
the right segment [ˆx2,1] buy good 2, and consumers in the middle segment [ˆx3, ˆx4] buy
the probabilistic good.
0
1
Good 1
Good 2
𝑥"!
𝑥""
Buy good 1
Buy good 2
Buy probabilistic good
𝑥"#
𝑥"$
图3: Consumer segments
Assume demand for good 1 and good 2 are the same. Let E(q, q0) represent the
demand function for good 1 or good 2, and E0(q, q0) represent the demand for the proba-
bilistic good. To determine these demand functions, we need to ﬁgure out the thresholds
ˆx1 ∼ˆx4.
5
Question 4 (15 pts): Show that, under the probabilistic selling strategy, if q0 ≤1
2, then
ˆx3 = ˆx1, ˆx4 = ˆx2; otherwise if q0 > 1
2, then E0(q, q0) = 0.
Answer 4: For consumer i, the utility of buying good 1, good 2 and the probabilistic
products are 1 −xi −q, xi −q and 1/2 −q0 respectively. She chooses the probabilistic
product if and only if
1
2 −q0 ≥1 −xi −q and 1
2 −q0 ≥xi −q and 1
2 −q0 ≥0.
When q0 > 1/2, the third inequality cannot hold, so E0(q, q0) = 0.
When q0 ≤1/2, the ﬁrst two inequalities give
1
2 −(q −q0) ≤xi ≤1
2 + (q −q0).
When xi = 1
2 −(q −q0), the consumer is indiﬀerent between good 1 and the probabilistic
good (their utilities are equal). When xi =
1
2 + (q −q0), the consumer is indiﬀerent
between good 2 and the probabilistic good. So we must have ˆx3 = ˆx1, ˆx4 = ˆx2, and
E0(q, q0) = 2(q −q0).
Questions 3 and 4 tell us that, if the seller decides to oﬀer the probabilistic good, she
must set q0 = 1
2 < q, in which case consumers are divided into three segments; otherwise,
the seller won’t oﬀer the probabilistic good, which becomes the traditional selling case.
Next, we determine the price q to maximize the proﬁt
G(q, q0) = 2(q −c) · E(q, q0) + (q0 −c) · E0(q, q0),
where q0 = 1
2.
Question 5 (15 pts): Given q0 = 1
2, ﬁnd the optimal price q∗(that is, the value of q
that maximizes G(q, q0)) and optimal proﬁt G∗= G(q∗, q0).
(Hint: Similar to the analysis of the traditional selling strategy, ﬁnd out the thresholds
ˆx1 and ˆx2 ﬁrst.)
Answer 5: As shown in Question 4, the thresholds are ˆx1 = ˆx3 = 1
2 −(q −q0), ˆx2 =
ˆx4 = 1
2 + (q −q0). Then we know that E(q, q0) = 1
2 −(q −q0) and E0(q, q0) = 2(q −q0).
Therefore,
G(q, q0) = (q −c) {1 −2(q −q0)} + 2(q0 −c)(q −q0)
= q −c −2(q −q0)2.
When q0 = 1/2, the optimal q is q∗= q0 + 1
4 =
3
4, and the optimal proﬁt is G∗=
q0 −c + 1
8 = 5
8 −c.
6
Question 6 (15 pts): Compare F ∗and G∗that you have obtained, and ﬁnd the condi-
tions under which the seller will adopt (采用) the probabilistic selling strategy and oﬀer
the probabilistic good.
Answer 6: By comparing F ∗= (1 −c)2/2 and G∗= 5
8 −c, we get that G∗> F ∗if and
only if 0 < c < 1/2.
Question 7 (10 pts): Based on the above analysis, can you give some explanation
about why sellers oﬀer probabilistic goods like “mystery boxes” to the market? Besides
the above analysis, can you list some other advantages of probabilistic selling?
7
