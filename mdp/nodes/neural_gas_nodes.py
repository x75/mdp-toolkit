from __future__ import division
from builtins import map
from builtins import range
from past.utils import old_div
from builtins import object
__docformat__ = "restructuredtext en"

from mdp import numx, numx_rand, utils, graph, Node

class _NGNodeData(object):
    """Data associated to a node in a Growing Neural Gas graph."""
    def __init__(self, pos, error=0.0, hits=0, label=None):
        # reference vector (spatial position)
        self.pos = pos
        # cumulative error
        self.cum_error = error
        self.hits = hits
        self.label = label

class _NGEdgeData(object):
    """Data associated to an edge in a Growing Neural Gas graph."""
    def __init__(self, age=0):
        self.age = age
    def inc_age(self):
        self.age += 1


class GrowingNeuralGasNode(Node):
    """Learn the topological structure of the input data by building a
    corresponding graph approximation.

    The algorithm expands on the original Neural Gas algorithm
    (see mdp.nodes NeuralGasNode) in that the algorithm adds new nodes are
    added to the graph as more data becomes available. Im this way,
    if the growth rate is appropriate, one can avoid overfitting  or
    underfitting the data.

    More information about the Growing Neural Gas algorithm can be found in
    B. Fritzke, A Growing Neural Gas Network Learns Topologies, in G. Tesauro,
    D. S. Touretzky, and T. K. Leen (editors), Advances in Neural Information
    Processing Systems 7, pages 625-632. MIT Press, Cambridge MA, 1995.

    **Attributes and methods of interest**

    - graph -- The corresponding `mdp.graph.Graph` object
    """
    def __init__(self, start_poss=None, eps_b=0.2, eps_n=0.006, max_age=50,
                 lambda_=100, alpha=0.5, d=0.995, max_nodes=2147483647,
                 input_dim=None, dtype=None):
        """Growing Neural Gas algorithm.

        :Parameters:

          start_poss
            sequence of two arrays containing the position of the
            first two nodes in the GNG graph. If unspecified, the
            initial nodes are chosen with a random position generated
            from a gaussian distribution with zero mean and unit
            variance.

          eps_b
            coefficient of movement of the nearest node to a new data
            point. Typical values are 0 < eps_b << 1 .

            Default: 0.2

          eps_n
            coefficient of movement of the neighbours of the nearest
            node to a new data point. Typical values are
            0 < eps_n << eps_b .

            Default: 0.006

          max_age
            remove an edge after `max_age` updates. Typical values are
            10 < max_age < lambda.

            Default: 50

          `lambda_`
            insert a new node after `lambda_` steps. Typical values are O(100).

            Default: 100

          alpha
            when a new node is inserted, multiply the error of the
            nodes from which it generated by 0<alpha<1. A typical value
            is 0.5.

            Default: 0.5

          d
            each step the error of the nodes are multiplied by 0<d<1.
            Typical values are close to 1.

            Default: 0.995

          max_nodes
            maximal number of nodes in the graph.

            Default: 2^31 - 1
        """
        self.graph = graph.Graph()
        self.tlen = 0

        #copy parameters
        (self.eps_b, self.eps_n, self.max_age, self.lambda_, self.alpha,
         self.d, self.max_nodes) = (eps_b, eps_n, max_age, lambda_, alpha,
                                    d, max_nodes)

        super(GrowingNeuralGasNode, self).__init__(input_dim, None, dtype)

        if start_poss is not None:
            if self.dtype is None:
                self.dtype = start_poss[0].dtype
            node1 = self._add_node(self._refcast(start_poss[0]))
            node2 = self._add_node(self._refcast(start_poss[1]))
            self._add_edge(node1, node2)

    def _set_input_dim(self, n):
        self._input_dim = n
        self.output_dim = n

    def _add_node(self, pos):
        node = self.graph.add_node(_NGNodeData(pos))
        return node

    def _add_edge(self, from_, to_):
        self.graph.add_edge(from_, to_, _NGEdgeData())

    def _get_nearest_nodes(self, x):
        """Return the two nodes in the graph that are nearest to x and their
        squared distances. (Return ([node1, node2], [dist1, dist2])"""
        # distance function
        def _distance_from_node(node):
            #return norm(node.data.pos-x)**2
            tmp = node.data.pos - x
            return utils.mult(tmp, tmp)
        g = self.graph
        # distances of all graph nodes from x
        distances = numx.array(list(map(_distance_from_node, g.nodes)))
        ids = distances.argsort()[:2]
        #nearest = [g.nodes[idx] for idx in ids]
        #return nearest, distances[ids]
        return (g.nodes[ids[0]], g.nodes[ids[1]]), distances.take(ids)

    def _move_node(self, node, x, eps):
        """Move a node by eps in the direction x."""
        # ! make sure that eps already has the right dtype
        node.data.pos += eps*(x - node.data.pos)

    def _remove_old_edges(self, edges):
        """Remove all edges older than the maximal age."""
        g, max_age = self.graph, self.max_age
        for edge in edges:
            if edge.data.age > max_age:
                g.remove_edge(edge)
                if edge.head.degree() == 0:
                    g.remove_node(edge.head)
                if edge.tail.degree() == 0:
                    g.remove_node(edge.tail)

    def _insert_new_node(self):
        """Insert a new node in the graph where it is more necessary (i.e.
        where the error is the largest)."""
        g = self.graph
        # determine the node with the highest error
        errors = [x.data.cum_error for x in g.nodes]
        qnode = g.nodes[numx.argmax(errors)]
        # determine the neighbour with the highest error
        neighbors = qnode.neighbors()
        errors = [x.data.cum_error for x in neighbors]
        fnode = neighbors[numx.argmax(errors)]
        # new node, halfway between the worst node and the worst of
        # its neighbors
        new_pos = 0.5*(qnode.data.pos + fnode.data.pos)
        new_node = self._add_node(new_pos)
        # update edges
        edges = qnode.get_edges(neighbor=fnode)
        g.remove_edge(edges[0])
        self._add_edge(qnode, new_node)
        self._add_edge(fnode, new_node)
        # update errors
        qnode.data.cum_error *= self.alpha
        fnode.data.cum_error *= self.alpha
        new_node.data.cum_error = 0.5*(qnode.data.cum_error+
                                       fnode.data.cum_error)

    def get_nodes_position(self):
        return numx.array([n.data.pos for n in self.graph.nodes],
                          dtype = self.dtype)

    def _train(self, input):
        g = self.graph
        d = self.d

        if len(g.nodes)==0:
            # if missing, generate two initial nodes at random
            # assuming that the input data has zero mean and unit variance,
            # choose the random position according to a gaussian distribution
            # with zero mean and unit variance
            normal = numx_rand.normal
            self._add_node(self._refcast(normal(0.0, 1.0, self.input_dim)))
            self._add_node(self._refcast(normal(0.0, 1.0, self.input_dim)))

        # loop on single data points
        for x in input:
            self.tlen += 1

            # step 2 - find the nearest nodes
            # dists are the squared distances of x from n0, n1
            (n0, n1), dists = self._get_nearest_nodes(x)

            # step 3 - increase age of the emanating edges
            for e in n0.get_edges():
                e.data.inc_age()

            # step 4 - update error
            n0.data.cum_error += numx.sqrt(dists[0])

            # step 5 - move nearest node and neighbours
            self._move_node(n0, x, self.eps_b)
            # neighbors undirected
            neighbors = n0.neighbors()
            for n in neighbors:
                self._move_node(n, x, self.eps_n)

            # step 6 - update n0<->n1 edge
            if n1 in neighbors:
                # should be one edge only
                edges = n0.get_edges(neighbor=n1)
                edges[0].data.age = 0
            else:
                self._add_edge(n0, n1)

            # step 7 - remove old edges
            self._remove_old_edges(n0.get_edges())

            # step 8 - add a new node each lambda steps
            if not self.tlen % self.lambda_ and len(g.nodes) < self.max_nodes:
                self._insert_new_node()

            # step 9 - decrease errors
            for node in g.nodes:
                node.data.cum_error *= d

    def nearest_neighbor(self, input):
        """Assign each point in the input data to the nearest node in
        the graph. Return the list of the nearest node instances, and
        the list of distances.
        Executing this function will close the training phase if
        necessary."""
        super(GrowingNeuralGasNode, self).execute(input)

        nodes = []
        dists = []
        for x in input:
            (n0, _), dist = self._get_nearest_nodes(x)
            nodes.append(n0)
            dists.append(numx.sqrt(dist[0]))
        return nodes, dists

class NeuralGasNode(GrowingNeuralGasNode):
    """Learn the topological structure of the input data by building a
    corresponding graph approximation (original Neural Gas algorithm).

    The Neural Gas algorithm was originally published in Martinetz, T. and
    Schulten, K.: A "Neural-Gas" Network Learns Topologies. In Kohonen, T.,
    Maekisara, K., Simula, O., and Kangas, J. (eds.), Artificial Neural
    Networks. Elsevier, North-Holland., 1991.

    **Attributes and methods of interest**

    - graph -- The corresponding `mdp.graph.Graph` object
    - max_epochs - maximum number of epochs until which to train.
    """
    def __init__(self, num_nodes = 10,
                       start_poss=None,
                       epsilon_i=0.3,               # initial epsilon
                       epsilon_f=0.05,              # final epsilon
                       lambda_i=30.,                # initial lambda
                       lambda_f=0.01,               # final lambda
                       max_age_i=20,                # initial edge lifetime
                       max_age_f=200,               # final edge lifetime
                       max_epochs=100,
                       n_epochs_to_train=None,
                       input_dim=None,
                       dtype=None):
        """Neural Gas algorithm.

        Default parameters taken from the original publication.

        :Parameters:

          start_poss
            sequence of two arrays containing the position of the
            first two nodes in the GNG graph. In unspecified, the
            initial nodes are chosen with a random position generated
            from a gaussian distribution with zero mean and unit
            variance.

          num_nodes
            number of nodes to use. Ignored if start_poss is given.

          epsilon_i, epsilon_f
            initial and final values of epsilon. Fraction of the distance
            between the closest node and the presented data point by which the
            node moves towards the data point in an adaptation step. Epsilon
            decays during training by e(t) = e_i(e_f/e_i)^(t/t_max) with t
            being the epoch.

          lambda_i, lambda_f
            initial and final values of lambda. Lambda influences how the
            weight change of nodes in the ranking decreases with lower rank. It 
            is sometimes called the "neighborhood factor". Lambda decays during
            training in the same manner as epsilon does.

          max_age_i, max_age_f
            Initial and final lifetime, after which an edge will be removed.
            Lifetime is measured in terms of adaptation steps, i.e.,
            presentations of data points. It decays during training like
            epsilon does.

          max_epochs
            number of epochs to train. One epoch has passed when all data points
            from the input have been presented once. The default in the original 
            publication was 40000, but since this has proven to be impractically
            high too high for many real-world data sets, we adopted a default
            value of 100.

          n_epochs_to_train
            number of epochs to train on each call. Useful for batch learning
            and for visualization of the training process. Default is to
            train once until max_epochs is reached.
        """

        self.graph = graph.Graph()

        if n_epochs_to_train is None:
            n_epochs_to_train = max_epochs

        #copy parameters
        self.num_nodes = num_nodes
        self.start_poss = start_poss
        self.epsilon_i = epsilon_i
        self.epsilon_f = epsilon_f
        self.lambda_i = lambda_i
        self.lambda_f = lambda_f
        self.max_age_i = max_age_i
        self.max_age_f = max_age_f
        self.max_epochs = max_epochs
        self.n_epochs_to_train = n_epochs_to_train

        super(GrowingNeuralGasNode, self).__init__(input_dim, None, dtype)

        if start_poss is not None:
            if self.num_nodes != len(start_poss):
                self.num_nodes = len(start_poss)
            if self.dtype is None:
                self.dtype = start_poss[0].dtype
            for node_ind in range(self.num_nodes):
                self._add_node(self._refcast(start_poss[node_ind]))
        self.epoch = 0


    def _train(self, input):
        g = self.graph

        if len(g.nodes) == 0:
            # if missing, generate num_nodes initial nodes at random
            # assuming that the input data has zero mean and unit variance,
            # choose the random position according to a gaussian distribution
            # with zero mean and unit variance
            normal = numx_rand.normal
            for _ in range(self.num_nodes):
                self._add_node(self._refcast(normal(0.0, 1.0, self.input_dim)))

        epoch = self.epoch
        e_i = self.epsilon_i
        e_f = self.epsilon_f
        l_i = self.lambda_i
        l_f = self.lambda_f
        T_i = float(self.max_age_i)
        T_f = float(self.max_age_f)
        max_epochs = float(self.max_epochs)
        remaining_epochs = self.n_epochs_to_train
        while remaining_epochs > 0:
            # reset permutation of data points
            di = numx.random.permutation(input)
            if epoch < max_epochs:
                denom = old_div(epoch,max_epochs)
            else:
                denom = 1.
            epsilon = e_i * ((old_div(e_f,e_i))**denom)
            lmbda = l_i * ((old_div(l_f,l_i))**denom)
            T = T_i * ((old_div(T_f,T_i))**denom)
            epoch += 1
            for x in di:
                # Step 1 rank nodes according to their distance to random point
                ranked_nodes = self._rank_nodes_by_distance(x)

                # Step 2 move nodes
                for rank,node in enumerate(ranked_nodes):
                    #TODO: cut off at some rank when using many nodes
                    #TODO: check speedup by vectorizing
                    delta_w = epsilon * numx.exp(old_div(-rank, lmbda)) * \
                                    (x - node.data.pos)
                    node.data.pos += delta_w

                # Step 3 update edge weight
                for e in g.edges:
                    e.data.inc_age()

                # Step 4 set age of edge between first two nodes to zero
                #  or create it if it doesn't exist.
                n0 = ranked_nodes[0]
                n1 = ranked_nodes[1]
                nn = n0.neighbors()
                if n1 in nn:
                    edges = n0.get_edges(neighbor=n1)
                    edges[0].data.age = 0  # should only be one edge
                else:
                    self._add_edge(n0, n1)

                # step 5 delete edges with age > max_age
                self._remove_old_edges(max_age=T)
            remaining_epochs -= 1
        self.epoch = epoch


    def _rank_nodes_by_distance(self, x):
        """Return the nodes in the graph in a list ranked by their squared
        distance to x. """

        #TODO: Refactor together with GNGNode._get_nearest_nodes

        # distance function
        def _distance_from_node(node):
            tmp = node.data.pos - x
            return utils.mult(tmp, tmp) # maps to mdp.numx.dot

        g = self.graph

        # distances of all graph nodes from x
        distances = numx.array(list(map(_distance_from_node, g.nodes)))
        ids = distances.argsort()
        ranked_nodes = [g.nodes[id] for id in ids]

        return ranked_nodes


    def _remove_old_edges(self, max_age):
        """Remove edges with age > max_age."""
        g = self.graph
        for edge in self.graph.edges:
            if edge.data.age > max_age:
                g.remove_edge(edge)
