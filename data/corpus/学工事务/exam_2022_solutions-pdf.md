# Exam_2022_solutions.pdf

所属通知：上海财经大学2024年交叉科学实验班报名表及往期试题
发布日期：2024-08-11
发布单位：上海财经大学信息管理与工程学院
原发布页：https://sime.sufe.edu.cn/1c/23/c10226a203811/page.htm
附件下载地址：https://sime.sufe.edu.cn/_upload/article/files/e2/1a/bcae6def4bf2bebb93ebff6806f1/b3ef8e60-9570-4a52-b815-91cb171fcad4.pdf

## 附件正文

Shanghai University of Finance and Economics
Entrance Examination for 2022 Interdisciplinary Sciences Elite Program
Date: September 02, 2022
Time: 6:00pm – 9:00pm
There are 10 questions, and total score is 100.
1
Background
The coronavirus disease 2019 (COVID-19) is a contagious disease caused by a par-
ticular virus. It has caused a global epidemic (疫情) up to the present year of 2022.
Besides studying the biological attributes of the virus, it is also critical to understand the
evolution of the epidemic in the population. There exists several classical models that
describe how certain types of diseases spread among people. Such epidemiological models
are useful tools to predict the future development of an epidemic.
2
A two-segment model
Figure 1: Division of population.
Assume there is an epidemic progressing in a population consisting of a fixed number
of N people. Suppose once an individual gets the disease, he/she becomes infectious (有
传染性的), and will not recover from the disease in the foreseeable future. However, the
disease is not vital, meaning no people will die from it. In light of such facts, we divide
the population into two disjoint (不相交的) groups: the susceptibles (待感染者) and the
infected (已感染者). See Figure 1 for an illustration of the division. We keep track of the
number of individuals from each group at the end of each day. In particular, at the end
1
of day t (t = 1, 2, . . . ), the susceptible group includes St people, and the infected group
includes It people. We also use S0 and I0 to denote the number from the two groups at
the beginning of day 1. We assume 0 < I0 < N. It can be seen easily that St + It = N
for all t = 0, 1, 2, . . . , where the population N is a constant that does not depend on t.
Now assume on day t ≥1, every susceptible individual has the same probability
βIt−1/N of getting infected due to contacts with people from the infected group. Here
β ∈(0, 1) is a constant. Also, the event whether a susceptible individual gets infected is
independent (独立于) of the event whether any other susceptible individual gets infected.
*On the average sense, the number of newly infected people on day t is counted
as βIt−1St−1/N. Figure 2 below demonstrates the transition of the two groups. Thus we
have the following recursive formula (递推式) for It:
It −It−1 = βIt−1St−1/N,
t = 1, 2, . . . .
(1)
Figure 2: Transition of two groups.
As it turns out, it is more convenient to record the proportions of the susceptibles
and the infected to the whole population, instead of recording their actual headcount. To
this end, we define the two proportions: st = St/N, it = It/N. In order to understand
how it and st changes day by day, we walk through some basic analysis.
Question 1 (10 pts): Using your knowledge of probability (概率知识), prove the sen-
tence marked with star. That is, prove that the average/expected number (平均数或者
期望数) of newly infected people on day t is βIt−1St−1/N.
Answer 1: For each susceptible individual, whether he/she gets infected on day t is a
Bernoulli random variable with success probability βIt−1/N. The total number of newly
infected people is then a binomial random variable with St−1 trials and success probability
βIt−1/N. Its expectation is βIt−1St−1/N.
Question 2 (10 pts): Write out two recursive formulas similar to (1), one for it and
one for st. The quantities It−1, It, St−1, St should disappear in both formulas. Further
show that, {it} is an non-decreasing sequence and {st} is a non-increasing sequence.
2
Answer 2: The two recursive formulas are:
it −it−1 = βit−1st−1
st −st−1 = −βit−1st−1.
Since we start from i0 ∈(0, 1), we are guaranteed that it −it−1 ≥0 and st −st−1 ≤0 for
all t.
Question 3 (10 pts): Suppose the epidemic starts with i0 ∈(0, 1/2). We count the
number of days until it exceeds 1 −i0. Let t∗be the largest t such that it ≤1 −i0. Prove
that
t∗≤
1 −2i0
i0(1 −i0)β .
(Hint: First try to find a lower bound (下界) for the daily increase it −it−1, then find an
upper bound (上界) for the total increase up to day t∗.)
Answer 3: The daily increase of {it} is βit−1st−1 = βit−1(1 −it−1), which is a quadratic
function of it−1. When it−1 ∈[i0, 1 −i0], we have that βit−1(1 −it−1) ≥βi0(1 −i0). This
holds true for the first t∗days. The total increment is then ≥t∗βi0(1 −i0). On the other
hand, the total increment is ≤1 −i0 −i0 = 1 −2i0 by the definition of t∗. We must then
have t∗βi0(1 −i0) ≤1 −2i0, which leads to the conclusion.
Question 4 (10 pts): Prove by contradiction (反证法) that, as t grows larger and larger,
it gets arbitrarily close to 1. The meaning of this result is, all people will eventually get
infected. You can start the proof by assuming it ≤1 −ϵ0 for all t with some small
constant ϵ0 > 0. A contradiction can be reached by an argument similar to Question 3.
Answer 4: Assume it ≤1 −ϵ0 for all t with some constant ϵ0 > 0. Then it ∈[i0, 1 −ϵ0]
for all t. The daily increase βit−1(1 −it−1) is then ≥min{βi0(1 −i0), βϵ0(1 −ϵ0)} := c0.
Since the total increment should be ≤1 −ϵ0 −i0, this amount of increase can last no
more than (1 −ϵ0 −i0)/c0 days. This leads to a contradiction to the fact that it ≤1 −ϵ0
for all large enough t.
3
Model with recovery
The model in the previous section ignores the fact that infected people may recover
from the disease. Now assume that an infected individual may recover from the disease,
and once recovered, he/she is no longer infectious. However, a recovered individual may
later catch the disease again. For each infected individual, we assume that he/she recovers
3
with probability α ∈(0, 1) independently on any given day. A more detailed explanation
is the following: if John belongs to the infected group at the beginning of day t, then he
recovers with probability α on day t. If he does recover, then he becomes a member of
the susceptible group at the end of day t. If he does not recover on day t, then he still
belongs to the infected group, and recovers with probability α on day t + 1. The events
whether he recovers on any particular day are mutually independent. On average, the
proportion (to the whole population) of newly recovered people on day t is just αit−1.
The transition of the two groups is illustrated in Figure 3.
We then have the recursive formulas
it −it−1 = βit−1st−1 −αit−1
(2)
st −st−1 = −βit−1st−1 + αit−1.
(3)
As usual, we assume i0 ∈(0, 1).
Figure 3: Transition of two groups with recovery.
One critical parameter in this system is R0 = β/α, which basically represents how
contagious the disease is. The future progression of the epidemic largely depends on
whether R0 < 1 or R0 > 1.
Question 5 (10 pts): Suppose R0 < 1. Explain why {it} is a non-increasing sequence.
Answer 5: Since β < α (from R0 < 1) and st−1 ≤1, it must be that βst−1 −α < 0 for
all t. From (2), we know that it ≤it−1.
Question 6 (10 pts): Suppose R0 > 1. Assume that the two variables it and st approach
their respective (各自的) steady states (平稳状态) i∗and s∗after a long enough period.
In plain words, the steady states i∗and s∗are two constants such that it ≈i∗and st ≈s∗
for all t ≥T (T is some big integer). If we know i∗∈(0, 1), try to find the values of i∗
and s∗.
Answer 6: For all t ≥T, we have it ≈i∗, st ≈s∗. Plugging these into (2) and (3),
we get 0 = βi∗s∗−αi∗. Since i∗> 0, we have s∗= α/β = 1/R0. The complement is
i∗= 1 −1/R0.
4
A more popular understanding of R0 is the average number of people who will get
the disease directly from the first infected individual.
Now suppose there is a large
population of N people who are completely healthy (susceptible). At the beginning of
day 1, there comes from outside an extra “patient zero”, who is infected by the disease.
By our previous assumption, every susceptible individual has probability β/N of getting
infected directly by “patient zero” on a given day, as long as “patient zero” has not
recovered. Suppose N is so large that, for a long long time, the infected only account for
an infinitesimal (极微小的) faction of the population. In other words, you can admit that
N = S0 ≈S1 ≈S2 ≈. . . . Also remember that “patient zero” recovers with probability
α on each day. We count the total number of people infected directly by “patient zero”
until he/she recovers.
Question 7 (10 pts): Show that the total average number of people who get infected
directly from “patient zero” is approximately R0.
Answer 7: On day t, “patient zero” is still infected with probability (1 −α)t−1. Then
the average number of people infected by “patient zero” is
β/N · St−1 · (1 −α)t−1 ≈β/N · N · (1 −α)t−1 = β(1 −α)t−1.
The cumulative average number is then approximately
∞
X
t=1
β(1 −α)t−1 = β/α = R0.
4
A three-segment model
Consider another scenario where people recovered from the disease get lifetime im-
munity. That is to say, recovered people will never get the disease again. They are not
infectious either. We then need to divide the population into three disjoint groups: the
susceptibles, the infected, and the recovered (已康复者). The proportion of people from
each group are denoted st, it and rt respectively. Remember st + it + rt = 1 for all t.
Figure 4 describes the transition between groups in this scenario.
Based on previous assumptions, we have the recursive formulas
it −it−1 = βit−1st−1 −αit−1
(4)
st −st−1 = −βit−1st−1
(5)
rt −rt−1 = αit−1.
(6)
5
Figure 4: Transition between three groups.
We assume i0 > 0, r0 = 0. We define the parameter R0 = β/α exactly the same as before,
and assume R0 > 1.
Question 8 (10 pts): Assume for the moment that the approximation (b −a)/a ≈
ln(b/a) holds for a > 0, b > 0. Use this approximation and recursive formulas (4)–(6) to
prove st ≈s0e−R0rt.
Answer 8: Combining (5) and (6), we get
st −st−1
st−1
= −R0(rt −rt−1).
By the given approximation, we have
ln st −ln st−1 ≈−R0(rt −rt−1).
Taking the sum, we get
ln st −ln s0 =
t
X
τ=1
(ln sτ −ln sτ−1) ≈−R0
t
X
τ=1
(rτ −rτ−1) = −R0(rt −r0) = −R0rt.
This leads to the desired result.
Question 9 (10 pts): Recall the definition of steady states in Question 6. Assume that
the three variables (it, st, rt) approach their respective steady states (i∗, s∗, r∗) after a long
enough period. Use the result of Question 8 and the three recursive formulas (4)–(6) to
prove: i∗= 0, s∗= 1 −r∗, and r∗satisfies the approximate equation
1 −r∗−s0e−R0r∗≈0.
Answer 9: Plugging the steady states into (6), we get 0 = αi∗. Thus i∗= 0, and
s∗= 1 −r∗. Also from the result of Question 8, we have s∗≈s0e−R0r∗. Therefore
1 −r∗≈s0e−R0r∗
6
5
A four-segment model
Consider the same scenario as Section 4, except for an additional feature. Let us
assume that the disease has an incubation period (潜伏期). The population is divided into
four disjoint groups: the susceptibles, the infected, the recovered, and the exposed (潜伏
者). The proportion of people from each group are denoted st, it, rt and et respectively.
Once a susceptible individual gets the disease, he/she becomes one of the exposed at
first.
The exposed people are not infectious.
When the incubation period ends for
an exposed individual, he/she becomes one of the infected, who are infectious. Each
exposed individual has probability δ ∈(0, 1) of becoming infected on any given day, so
that the average proportion of newly infected people on day t is δet−1. See Figure 5 for
a description of such transition.
Figure 5: Transition between four groups.
Question 10 (10 pts): Write out the four recursive formulas for st, it, rt and et.
Answer 10: The formulas are
st −st−1 = −βit−1st−1
it −it−1 = δet−1 −αit−1
rt −rt−1 = αit−1
et −et−1 = βit−1st−1 −δet−1.
7
