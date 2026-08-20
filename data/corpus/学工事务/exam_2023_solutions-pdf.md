# Exam_2023_solutions.pdf

所属通知：上海财经大学2024年交叉科学实验班报名表及往期试题
发布日期：2024-08-11
发布单位：上海财经大学信息管理与工程学院
原发布页：https://sime.sufe.edu.cn/1c/23/c10226a203811/page.htm
附件下载地址：https://sime.sufe.edu.cn/_upload/article/files/e2/1a/bcae6def4bf2bebb93ebff6806f1/b73b16cf-06a9-4927-95f9-7e76f2122069.pdf

## 附件正文

Shanghai University of Finance and Economics
Entrance Examination for 2023 Interdisciplinary Sciences Elite Program
Date: September 01, 2023
Time: 6:00pm – 9:00pm
There are 10 questions, and total score is 100.
1
Background
Inventory management (库存管理) is the process of planning and controlling the
flow of goods in and out of a business. It helps to ensure that the business has enough
products to meet customer demand, while avoiding the waste and expense of overstocking
or understocking. Inventory management involves deciding when to order new products,
how many to order, and how to store them efficiently. Suppose you own a bookstore that
sells books, magazines, and stationery (文具). You want to keep track of how many items
you have in stock (存货), how much they cost, and how fast they sell. You also want to
avoid the problems of overstocking or understocking your products. If you store too few
products, you may run out of stock (缺货) and lose sales, profits, and competitive edge.
If you store too many products, you may waste money and space, and risk having unsold
or damaged goods.
One common inventory problem is how to replenish (补充) inventory when it is
depleted by customer demand.
This problem can be modeled by assuming that the
demand rate (单位时间需求量) for a product is constant and known, denoted by R, and
that the product is ordered in batches. The costs involved in this problem are: (1). the
cost of holding each unit of product in inventory per unit time, C1; (2). the cost of
being unable to meet each unit of customer demand per unit time, C2; (3). the fixed
cost of placing an order for a batch of (一批) products, C3; (4). the cost of producing or
purchasing each unit of product, K.
The goal of inventory management is to find the best ordering policy that minimizes
the total cost per unit time, while satisfying customer demand. This policy specifies when
to order a new batch of products, and how many units to order each time.
1
2
Inventory replenishment with zero shortage and
instant delivery
To simplify the problem, we first assume that we never run out of stock. In other
words, we set the shortage cost, C2, to be very high. We also assume that we can order a
batch of products and receive them instantly when our inventory level reaches zero. This
way, we can avoid any delays or uncertainties in the supply chain.
Let t be the time interval between two consecutive orders, and Q be the quantity of
products ordered each time. Figure 1 shows how the inventory level changes over time
under this policy. We start with an inventory level of zero, and order Q units at time
zero. Then, we sell the products at a constant rate of R units per unit time, until the
inventory level drops to zero again. At this point, we order another batch of Q units, and
repeat the cycle.
图1: Inventory level over time when we order and receive products immediately.
We know the values of R, C1, C3 and K, which are the demand rate, the holding cost
per unit product per unit time, the fixed cost per order, and the unit cost per product,
respectively. Our goal is to find the optimal value of Q, which minimizes the total cost
per unit time.
To help you understand the notations more clearly, we give you an example of how to
calculate the total cost per cycle. The production or ordering cost per cycle is C3 + KQ.
The holding cost per cycle is C1Qt/2 = C1Q2/2/R. Therefore, the total cost per cycle is
2
C3 + KQ + C1Q2/2/R.
Question 1. What is the expression for the total cost per unit time, denoted by C(Q),
as a function of Q?
Answer 1: The total cost per unit time is
C(Q) = C3 + KQ
t
+ C1Q/2 = C3 + KQ
Q/R
+ C1Q
2
= C3R
Q
+ KR + C1Q
2 .
Now we determine when and by how much to replenish inventory through minimizing
the total cost per unit time.
Question 2. What is the optimal value of Q, denoted by Q∗, that minimizes C(Q)?
What is the corresponding value of t, denoted by t∗?
Answer 2: The optimal value of Q is given by
Q∗=
r
2C3R
C1
.
The corresponding t∗is t∗= Q∗/R =
q
2C3
C1R.
3
Inventory replenishment with stockouts and back-
orders
Sometimes, it may be beneficial to allow some stockouts (缺货), or planned shortages,
in inventory management. This means that we are willing to accept a delay in fulfilling
some customer orders, if the holding cost of inventory (C1) is too high compared to the
shortage cost (C2). The shortage cost is the cost of losing customer satisfaction or loyalty
due to unavailability of products.
When we have stockouts, we keep track of the customer orders that are not met, and
we call them backorders. Backorders are orders that are placed by customers but cannot
be delivered immediately because the product is out of stock. The business promises to
deliver the product as soon as possible, but the customer has to wait until then. This
can affect the customer’s perception of the business and its service quality. We fill the
backorders as soon as we receive a new batch of products. In this case, the inventory
level over time looks like Figure 2. It shows that when the inventory level reaches zero,
we do not order immediately, but wait for some time, t1, until we order a batch of Q
3
units. During this time, we accumulate backorders, which are filled when the new batch
arrives. Then we sell the remaining at a constant rate of R units per unit time. Note
that there is no holding cost during the period (0, t1).
图2: Inventory level over time when we allow some stockouts and backorders.
We know the values of R, C1, C2, C3 and K, which are the demand rate, the holding
cost per unit product per unit time, the shortage cost per unit product per unit time,
the fixed cost per order, and the unit cost per product, respectively. Our goal is to find
the optimal values of t1 and Q, which minimize the total cost per unit time.
Question 3.
What is the expression for the total cost per unit time, denoted by
C(t1, Q), as a function of t1 and Q?
Answer 3: The production or ordering cost per cycle C3 + KQ. The holding cost per
cycle is C1 ∗A/2 ∗(t −t1) = C1 ∗R ∗(t −t1)2/2 = C1 ∗R ∗(Q/R −t1)2/2. The shortage
cost per cycle is C2 ∗B/2 ∗t1 = C2 ∗R ∗t2
1/2. Therefore, the total cost per unit time is
C(t1, Q)
=
C3 + KQ
t
+ C1R(Q/R −t1)2
2t
+ C2Rt2
1
2t
=
C3R
Q
+ KR + C1(Q −t1R)2
2Q
+ C2R2t2
1
2Q
.
Now we minimize the total cost per unit time to determine when and by how much
to replenish inventory.
4
Question 4. For each fixed Q, what is the optimal value of t1, denoted by t∗
1(Q), that
minimizes C(t1, Q)?
Answer 4: For each Q, the optimal t1 is given by
t∗
1(Q) =
C1Q
(C1 + C2)R.
Question 5. What are the optimal values of t1 and Q, denoted by t∗and Q∗, that
minimize C(t1, Q)?
Answer 5: Substituting t∗
1(Q) =
C1Q
(C1+C2)R into C(t∗
1(Q), Q), we have,
C(t∗
1(Q), Q)
=
C3R
Q
+ KR + C1(Q −αQ)2
2Q
+ C2α2Q2
2Q
=
C3R
Q
+ KR + C1(1 −α)2Q
2
+ C2α2Q
2
,
where α = C1/(C1 + C2). Then the optimal Q is given by
Q∗=
s
2C3R(C1 + C2)
C1C2
.
The corresponding t∗is
t∗=
s
2C1C3
RC2(C1 + C2).
4
Inventory replenishment with finite production rate
Sometimes, we cannot order a batch of products and receive them instantly. Instead,
we need to produce the products ourselves, or wait for the supplier to produce them for
us. We assume that we can start the production process whenever we want, but it takes
some time to complete. We also assume that we can store the products in our inventory
as soon as they are produced, without any delay in transportation. Let P be the constant
production rate, which is higher than R. In this case, the inventory level over time looks
like Figure 3.
We know the values of R, P, C1, C2, C3 and K, which are the demand rate, the
production rate, the holding cost per unit product per unit time, the shortage cost per
5
图3: Inventory level over time when we have a delay in producing or receiving products.
unit product per unit time, the fixed cost per order, and the unit cost per product,
respectively. Our goal is to find the optimal values of t1 and Q, which minimize the total
cost per unit time.
Question 6.
What is the expression for the total cost per unit time, denoted by
C(t1, Q), as a function of t1 and Q?
Answer 6: First of all, Q = Rt, B = Rt1 = (P−R)(t2−t1), A = R(t−t3) = (P−R)(t3−t2).
Then we have t = Q/R, t2 = Pt1/(P −R), and t3 = t1 + R/Pt = t1 + Q/P.
The production or ordering cost per cycle C3 + KQ. The holding cost per cycle is
C1 ∗A/2 ∗(t −t2) = C1 ∗(Q −Rt1 −RQ/P) ∗(Q/R −Pt1/(P −R))/2. The shortage
cost per cycle is C2 ∗B/2 ∗t2 = C2 ∗P ∗R ∗t2
1/(P −R)/2. Therefore, the total cost per
unit time is
C(t1, Q)
=
C3 + KQ
t
+ C1(Q −Rt1 −RQ/P)(Q/R −Pt1/(P −R))
2t
+
C2PRt2
1
2t(P −R)
=
C3R
Q
+ KR + C1(Q −βRt1)2
2βQ
+ C2βR2t2
1
2Q
,
where β = P/(P −R).
Now we minimize the total cost per unit time to determine when and by how much
to replenish inventory.
Question 7. For each fixed Q, what is the optimal value of t1, denoted by t∗
1(Q), that
minimizes C(t1, Q)?
6
Answer 7: For each Q, the optimal t1 is given by
t∗
1(Q) =
C1Q
β(C1 + C2)R.
Question 8. What are the optimal values of t1 and Q, denoted by t∗and Q∗, that
minimize C(t1, Q)?
Answer 8: Substituting t∗
1(Q) =
C1Q
β(C1+C2)R into C(t∗
1(Q), Q), we have,
C(t∗
1(Q), Q)
=
C3R
Q
+ KR + C1(Q −αQ)2
2βQ
+ C2α2Q
2Qβ
=
C3R
Q
+ KR + C1(1 −α)2Q
2β
+ C2α2Q
2β
,
where α = C1/(C1 + C2). Then the optimal Q is given by
Q∗=
s
2C3R(C1 + C2)
C1C2
r
P
P −R.
The corresponding t∗is
t∗=
s
2C1C3
RC2(C1 + C2)
r
P
P −R.
5
Inventory management with stochastic demand
So far, we have assumed that the demand for the product is constant and known in
advance. However, in reality, the demand may vary from day to day, and we may not be
able to predict it accurately. In this case, we say that the demand is stochastic, meaning
that it is random and follows a certain probability distribution.
For simplicity, we only consider a single-period inventory problem, such as a newsven-
dor who sells newspapers every day. The newsvendor needs to decide how many news-
papers to order before knowing the actual demand for that day, and then sell them at a
fixed price per unit. At the end of the day, the newsvendor earns a profit of k dollars for
each newspaper sold, and incurs a cost of h dollars for each newspaper left unsold.
The newsvendor faces a trade-off between ordering too many newspapers and having
excess inventory, or ordering too few newspapers and missing potential sales. The goal is
to find the optimal order quantity, Q∗, that maximizes the expected profit per day.
7
Let R be the random variable that represents the demand for newspapers per day.
Let P(r) be the probability that the demand is equal to r, where r = 0, 1, . . .. We assume
that P∞
r=0 P(r) = 1.
Question 9.
What is the expected revenue if the order quantity is Q?
(Hint: Use
the formula for the expected value of a function of a random variable: E[f(R)] =
P∞
r=0 f(r)P(r).)
When the demand is r, the revenue is kr −h(Q−r) if r ≤Q and kQ if r > Q. Therefore,
the expected revenue is
Q
X
r=0
{kr −h(Q −r)}P(r) +
∞
X
r=Q+1
kQP(r)
=
Q
X
r=0
{kr −h(Q −r)}P(r) +
∞
X
r=Q+1
{k(Q −r)}P(r) +
∞
X
r=Q+1
krP(r)
=
kE(R) −
∞
X
r=Q+1
{k(r −Q)}P(r) −
Q
X
r=0
{h(Q −r)}P(r).
Question 10. Define F(Q) = PQ
r=0 P(r). This is the probability that the demand is
less than or equal to Q. Show that the optimal order quantity, Q∗, can be determined by
finding the value of Q such that
F(Q −1) <
k
k + h ≤F(Q).
Let C(Q) be the difference between kE(R) and the expected revenue when the order
quantity is Q. That is,
C(Q) =
∞
X
r=Q+1
{k(r −Q)}P(r) +
Q
X
r=0
{h(Q −r)}P(r).
Then we have
C(Q + 1) −C(Q) = (k + h)

F(Q) −
k
k + h

.
This implies that when F(Q) <
k
k+h, C(Q + 1) < C(Q), while when F(Q) ≥
k
k+h,
C(Q + 1) ≥C(Q). Therefore, when F(Q∗−1) <
k
k+h ≤F(Q∗), C(Q∗) attains the
minimum of C(Q), or equivalently, the revenue attains the maximum.
8
