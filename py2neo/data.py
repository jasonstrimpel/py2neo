#!/usr/bin/env python
# -*- encoding: utf-8 -*-

# Copyright 2011-2018, Nigel Small
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from io import StringIO
from itertools import chain
from uuid import uuid4

from py2neo.cypher.writing import LabelSetView, cypher_repr, cypher_str
from py2neo.internal.collections import is_collection
from py2neo.internal.compat import integer_types, numeric_types, string_types, ustr, xstr
from py2neo.internal.operations import create_subgraph, merge_subgraph, delete_subgraph, separate_subgraph, \
    pull_subgraph, push_subgraph
from py2neo.storage import PropertyDict


def html_escape(s):
    return (s.replace(u"&", u"&amp;")
             .replace(u"<", u"&lt;")
             .replace(u">", u"&gt;")
             .replace(u'"', u"&quot;")
             .replace(u"'", u"&#039;"))


def order(graph_structure):
    """ Count the number of nodes in a graph structure.
    """
    try:
        return graph_structure.__graph_order__()
    except AttributeError:
        raise TypeError("Object is not a graph structure")


def size(graph_structure):
    """ Count the number of relationships in a graph structure.
    """
    try:
        return graph_structure.__graph_size__()
    except AttributeError:
        raise TypeError("Object is not a graph structure")


def walk(*walkables):
    """ Traverse over the arguments supplied, yielding the entities
    from each in turn.

    :arg walkables: sequence of walkable objects
    """
    if not walkables:
        return
    walkable = walkables[0]
    try:
        entities = walkable.__walk__()
    except AttributeError:
        raise TypeError("Object %r is not walkable" % walkable)
    for entity in entities:
        yield entity
    end_node = walkable.end_node
    for walkable in walkables[1:]:
        try:
            if end_node == walkable.start_node:
                entities = walkable.__walk__()
                end_node = walkable.end_node
            elif end_node == walkable.end_node:
                entities = reversed(list(walkable.__walk__()))
                end_node = walkable.start_node
            else:
                raise ValueError("Cannot append walkable %r "
                                 "to node %r" % (walkable, end_node))
        except AttributeError:
            raise TypeError("Object %r is not walkable" % walkable)
        for i, entity in enumerate(entities):
            if i > 0:
                yield entity


class Subgraph(object):
    """ Arbitrary, unordered collection of nodes and relationships.
    """

    def __init__(self, nodes=None, relationships=None):
        self.__nodes = frozenset(nodes or [])
        self.__relationships = frozenset(relationships or [])
        self.__nodes |= frozenset(chain(*(r.nodes for r in self.__relationships)))
        if not self.__nodes:
            raise ValueError("Subgraphs must contain at least one node")

    # def __repr__(self):
    #     return "Subgraph({" + ", ".join(map(repr, self.nodes)) + "}, {" + ", ".join(map(repr, self.relationships)) + "})"

    def __eq__(self, other):
        try:
            return order(self) == order(other) and size(self) == size(other) and \
                   self.nodes == other.nodes and self.relationships == other.relationships
        except (AttributeError, TypeError):
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        value = 0
        for entity in self.__nodes:
            value ^= hash(entity)
        for entity in self.__relationships:
            value ^= hash(entity)
        return value

    def __graph_order__(self):
        """ Total number of unique nodes.
        """
        return len(self.__nodes)

    def __graph_size__(self):
        """ Total number of unique relationships.
        """
        return len(self.__relationships)

    def __len__(self):
        return len(self.__relationships)

    def __iter__(self):
        return iter(self.__relationships)

    def __bool__(self):
        return bool(self.__relationships)

    def __nonzero__(self):
        return bool(self.__relationships)

    def __or__(self, other):
        return Subgraph(set(self.nodes) | set(other.nodes), set(self.relationships) | set(other.relationships))

    def __and__(self, other):
        return Subgraph(set(self.nodes) & set(other.nodes), set(self.relationships) & set(other.relationships))

    def __sub__(self, other):
        r = set(self.relationships) - set(other.relationships)
        n = (set(self.nodes) - set(other.nodes)) | set().union(*(set(rel.nodes) for rel in r))
        return Subgraph(n, r)

    def __xor__(self, other):
        r = set(self.relationships) ^ set(other.relationships)
        n = (set(self.nodes) ^ set(other.nodes)) | set().union(*(set(rel.nodes) for rel in r))
        return Subgraph(n, r)

    def __db_create__(self, tx):
        create_subgraph(tx, self)

    def __db_delete__(self, tx):
        delete_subgraph(tx, self)

    def __db_merge__(self, tx, primary_label=None, primary_key=None):
        merge_subgraph(tx, self, primary_label, primary_key)

    def __db_pull__(self, tx):
        pull_subgraph(tx, self)

    def __db_push__(self, tx):
        push_subgraph(tx, self)

    def __db_separate__(self, tx):
        separate_subgraph(tx, self)

    @property
    def nodes(self):
        """ Set of all nodes.
        """
        return self.__nodes

    @property
    def relationships(self):
        """ Set of all relationships.
        """
        return self.__relationships

    @property
    def labels(self):
        """ Set of all node labels.
        """
        return frozenset(chain(*(node.labels for node in self.__nodes)))

    def types(self):
        """ Set of all relationship types.
        """
        return frozenset(type(rel).__name__ for rel in self.__relationships)

    def keys(self):
        """ Set of all property keys.
        """
        return (frozenset(chain(*(node.keys() for node in self.__nodes))) |
                frozenset(chain(*(rel.keys() for rel in self.__relationships))))


class Walkable(Subgraph):
    """ A subgraph with added traversal information.
    """

    def __init__(self, iterable):
        self.__sequence = tuple(iterable)
        Subgraph.__init__(self, self.__sequence[0::2], self.__sequence[1::2])

    def __repr__(self):
        return xstr(cypher_repr(self))

    def __eq__(self, other):
        try:
            other_walk = tuple(walk(other))
        except TypeError:
            return False
        else:
            return tuple(walk(self)) == other_walk

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        value = 0
        for item in self.__sequence:
            value ^= hash(item)
        return value

    def __len__(self):
        return (len(self.__sequence) - 1) // 2

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop = index.start, index.stop
            if start is not None:
                if start < 0:
                    start += len(self)
                start *= 2
            if stop is not None:
                if stop < 0:
                    stop += len(self)
                stop = 2 * stop + 1
            return Walkable(self.__sequence[start:stop])
        elif index < 0:
            return self.__sequence[2 * index]
        else:
            return self.__sequence[2 * index + 1]

    def __iter__(self):
        for relationship in self.__sequence[1::2]:
            yield relationship

    def __add__(self, other):
        if other is None:
            return self
        return Walkable(walk(self, other))

    def __walk__(self):
        """ Traverse and yield all nodes and relationships in this
        object in order.
        """
        return iter(self.__sequence)

    @property
    def start_node(self):
        """ The first node encountered on a :func:`.walk` of this object.
        """
        return self.__sequence[0]

    @property
    def end_node(self):
        """ The last node encountered on a :func:`.walk` of this object.
        """
        return self.__sequence[-1]

    @property
    def nodes(self):
        """ The sequence of nodes over which a :func:`.walk` of this
        object will traverse.
        """
        return self.__sequence[0::2]

    @property
    def relationships(self):
        """ The sequence of relationships over which a :func:`.walk`
        of this object will traverse.
        """
        return self.__sequence[1::2]


class Entity(PropertyDict, Walkable):
    """ Base class for objects that can be optionally bound to a remote resource. This
    class is essentially a container for a :class:`.Resource` instance.
    """

    graph = None
    identity = None

    def __init__(self, iterable, properties):
        Walkable.__init__(self, iterable)
        PropertyDict.__init__(self, properties)
        uuid = str(uuid4())
        while "0" <= uuid[-7] <= "9":
            uuid = str(uuid4())
        self.__uuid__ = uuid

    def __repr__(self):
        return Walkable.__repr__(self)

    def __bool__(self):
        return len(self) > 0

    def __nonzero__(self):
        return len(self) > 0

    @property
    def __name__(self):
        name = None
        if name is None and "__name__" in self:
            name = self["__name__"]
        if name is None and "name" in self:
            name = self["name"]
        if name is None and self.identity is not None:
            name = u"_" + ustr(self.identity)
        return name or u""


class Node(Entity):
    """ A node is a fundamental unit of data storage within a property
    graph that may optionally be connected, via relationships, to
    other nodes.

    All positional arguments passed to the constructor are interpreted
    as labels and all keyword arguments as properties::

        >>> from py2neo import Node
        >>> a = Node("Person", name="Alice")

    """

    @classmethod
    def cast(cls, obj):
        """ Cast an arbitrary object to a :class:`Node`. This method
        takes its best guess on how to interpret the supplied object
        as a :class:`Node`.
        """
        if obj is None or isinstance(obj, Node):
            return obj

        def apply(x):
            if isinstance(x, dict):
                inst.update(x)
            elif is_collection(x):
                for item in x:
                    apply(item)
            elif isinstance(x, string_types):
                inst.add_label(ustr(x))
            else:
                raise TypeError("Cannot cast %s to Node" % obj.__class__.__name__)

        inst = Node()
        apply(obj)
        return inst

    def __init__(self, *labels, **properties):
        self._remote_labels = frozenset()
        self._labels = set(labels)
        Entity.__init__(self, (self,), properties)
        self._stale = set()

    def __eq__(self, other):
        if self is other:
            return True
        try:
            if any(x is None for x in [self.graph, other.graph, self.identity, other.identity]):
                return False
            return issubclass(type(self), Node) and issubclass(type(other), Node) and self.graph == other.graph and self.identity == other.identity
        except (AttributeError, TypeError):
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        if self.graph and self.identity:
            return hash(self.graph.database) ^ hash(self.graph.name) ^ hash(self.identity)
        else:
            return hash(id(self))

    def __getitem__(self, item):
        if self.graph is not None and self.identity is not None and "properties" in self._stale:
            self.graph.pull(self)
        return Entity.__getitem__(self, item)

    def __ensure_labels(self):
        if self.graph is not None and self.identity is not None and "labels" in self._stale:
            self.graph.pull(self)

    @property
    def labels(self):
        """ Set of all node labels.
        """
        self.__ensure_labels()
        return LabelSetView(self._labels)

    def has_label(self, label):
        self.__ensure_labels()
        return label in self._labels

    def add_label(self, label):
        self.__ensure_labels()
        self._labels.add(label)

    def remove_label(self, label):
        self.__ensure_labels()
        self._labels.discard(label)

    def clear_labels(self):
        self.__ensure_labels()
        self._labels.clear()

    def update_labels(self, labels):
        self.__ensure_labels()
        self._labels.update(labels)


class Relationship(Entity):
    """ A relationship represents a typed connection between a pair of nodes.

    The positional arguments passed to the constructor identify the nodes to
    relate and the type of the relationship. Keyword arguments describe the
    properties of the relationship::

        >>> from py2neo import Node, Relationship
        >>> a = Node("Person", name="Alice")
        >>> b = Node("Person", name="Bob")
        >>> a_knows_b = Relationship(a, "KNOWS", b, since=1999)

    This class may be extended to allow relationship types names to be
    derived from the class name. For example::

        >>> WORKS_WITH = Relationship.type("WORKS_WITH")
        >>> a_works_with_b = WORKS_WITH(a, b)
        >>> a_works_with_b
        (Alice)-[:WORKS_WITH {}]->(Bob)

    """

    @staticmethod
    def type(name):
        """ Return the :class:`.Relationship` subclass corresponding to a
        given name.

        :param name: relationship type name
        :returns: `type` object
        """
        for s in Relationship.__subclasses__():
            if s.__name__ == name:
                return s
        return type(xstr(name), (Relationship,), {})

    @classmethod
    def cast(cls, obj, entities=None):

        def get_type(r):
            if isinstance(r, string_types):
                return r
            elif isinstance(r, Relationship):
                return type(r).__name__
            elif isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], string_types):
                return r[0]
            else:
                raise ValueError("Cannot determine relationship type from %r" % r)

        def get_properties(r):
            if isinstance(r, string_types):
                return {}
            elif isinstance(r, Relationship):
                return dict(r)
            elif hasattr(r, "properties"):
                return r.properties
            elif isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], string_types):
                return dict(r[1])
            else:
                raise ValueError("Cannot determine properties from %r" % r)

        if isinstance(obj, Relationship):
            return obj
        elif isinstance(obj, tuple):
            if len(obj) == 3:
                start_node, t, end_node = obj
                properties = get_properties(t)
            elif len(obj) == 4:
                start_node, t, end_node, properties = obj
                properties = dict(get_properties(t), **properties)
            else:
                raise TypeError("Cannot cast relationship from %r" % obj)
        else:
            raise TypeError("Cannot cast relationship from %r" % obj)

        if entities:
            if isinstance(start_node, integer_types):
                start_node = entities[start_node]
            if isinstance(end_node, integer_types):
                end_node = entities[end_node]
        return Relationship(start_node, get_type(t), end_node, **properties)

    def __init__(self, *nodes, **properties):
        n = []
        for value in nodes:
            if isinstance(value, string_types):
                n.append(value)
            else:
                n.append(Node.cast(value))

        num_args = len(n)
        if num_args == 0:
            raise TypeError("Relationships must specify at least one endpoint")
        elif num_args == 1:
            # Relationship(a)
            # self._type = self.default_type()
            n = (n[0], n[0])
        elif num_args == 2:
            if n[1] is None or isinstance(n[1], string_types):
                # Relationship(a, "TO")
                # self._type = n[1]
                self.__class__ = Relationship.type(n[1])
                n = (n[0], n[0])
            else:
                # Relationship(a, b)
                # self._type = self.default_type()
                n = (n[0], n[1])
        elif num_args == 3:
            # Relationship(a, "TO", b)
            # self._type = n[1]
            self.__class__ = Relationship.type(n[1])
            n = (n[0], n[2])
        else:
            raise TypeError("Hyperedges not supported")
        Entity.__init__(self, (n[0], self, n[1]), properties)

        self._stale = set()

    def __eq__(self, other):
        if self is other:
            return True
        try:
            if any(x is None for x in [self.graph, other.graph, self.identity, other.identity]):
                try:
                    return type(self) is type(other) and list(self.nodes) == list(other.nodes) and dict(self) == dict(other)
                except (AttributeError, TypeError):
                    return False
            return issubclass(type(self), Relationship) and issubclass(type(other), Relationship) and self.graph == other.graph and self.identity == other.identity
        except (AttributeError, TypeError):
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.nodes) ^ hash(type(self))


class Path(Walkable):
    """ A sequence of nodes connected by relationships that may
    optionally be bound to remote counterparts in a Neo4j database.

        >>> from py2neo import Node, Path
        >>> alice, bob, carol = Node(name="Alice"), Node(name="Bob"), Node(name="Carol")
        >>> abc = Path(alice, "KNOWS", bob, Relationship(carol, "KNOWS", bob), carol)
        >>> abc
        <Path order=3 size=2>
        >>> abc.nodes
        (<Node labels=set() properties={'name': 'Alice'}>,
         <Node labels=set() properties={'name': 'Bob'}>,
         <Node labels=set() properties={'name': 'Carol'}>)
        >>> abc.relationships
        (<Relationship type='KNOWS' properties={}>,
         <Relationship type='KNOWS' properties={}>)
        >>> dave, eve = Node(name="Dave"), Node(name="Eve")
        >>> de = Path(dave, "KNOWS", eve)
        >>> de
        <Path order=2 size=1>
        >>> abcde = Path(abc, "KNOWS", de)
        >>> abcde
        <Path order=5 size=4>
        >>> for relationship in abcde.relationships:
        ...     print(relationship)
        ({name:"Alice"})-[:KNOWS]->({name:"Bob"})
        ({name:"Carol"})-[:KNOWS]->({name:"Bob"})
        ({name:"Carol"})-[:KNOWS]->({name:"Dave"})
        ({name:"Dave"})-[:KNOWS]->({name:"Eve"})

    """

    def __init__(self, *entities):
        entities = list(entities)
        for i, entity in enumerate(entities):
            if isinstance(entity, Entity):
                continue
            elif entity is None:
                entities[i] = Node()
            elif isinstance(entity, dict):
                entities[i] = Node(**entity)
        for i, entity in enumerate(entities):
            try:
                start_node = entities[i - 1].end_node
                end_node = entities[i + 1].start_node
            except (IndexError, AttributeError):
                pass
            else:
                if isinstance(entity, string_types):
                    entities[i] = Relationship(start_node, entity, end_node)
                elif isinstance(entity, tuple) and len(entity) == 2:
                    t, properties = entity
                    entities[i] = Relationship(start_node, t, end_node, **properties)
        Walkable.__init__(self, walk(*entities))


class Table(list):
    """ Immutable list of records.
    """

    def __init__(self, records, keys=None):
        super(Table, self).__init__(map(tuple, records))
        if keys is None:
            try:
                k = records.keys()
            except AttributeError:
                raise ValueError("Missing keys")
        else:
            k = list(map(ustr, keys))
        width = len(k)
        t = [set() for _ in range(width)]
        o = [False] * width
        for record in self:
            for i, value in enumerate(record):
                if value is None:
                    o[i] = True
                else:
                    t[i].add(type(value))
        f = []
        for i, _ in enumerate(k):
            f.append({
                "type": t[i].copy().pop() if len(t[i]) == 1 else tuple(t[i]),
                "numeric": all(t_ in numeric_types for t_ in t[i]),
                "optional": o[i],
            })
        self._keys = k
        self._fields = f

    def __repr__(self):
        s = StringIO()
        self.write(file=s, header=True)
        return s.getvalue()

    def _repr_html_(self):
        s = StringIO()
        self.write_html(file=s, header=True)
        return s.getvalue()

    def keys(self):
        """ The list of field names for this table.

        :return:
        """
        return list(self._keys)

    def field(self, key):
        """ Dictionary of metadata for a given field.

        :param key:
        :return:
        """
        if isinstance(key, integer_types):
            return self._fields[key]
        elif isinstance(key, string_types):
            try:
                index = self._keys.index(key)
            except ValueError:
                raise KeyError(key)
            else:
                return self._fields[index]
        else:
            raise TypeError(key)

    def _range(self, skip, limit):
        if skip is None:
            skip = 0
        if limit is None or skip + limit > len(self):
            return range(skip, len(self))
        else:
            return range(skip, skip + limit)

    def write(self, file=None, header=None, skip=None, limit=None, auto_align=True,
              padding=1, separator=u"|", newline=u"\r\n"):
        """ Write data to a human-readable table.

        :param file:
        :param header:
        :param skip:
        :param limit:
        :param auto_align:
        :param padding:
        :param separator:
        :param newline:
        :return:
        """
        from click import secho

        space = u" " * padding
        widths = [3 if header else 0] * len(self._keys)

        def calc_widths(values, **_):
            strings = [cypher_str(value).splitlines(False) for value in values]
            for i, s in enumerate(strings):
                w = max(map(len, s)) if s else 0
                if w > widths[i]:
                    widths[i] = w

        def write_line(values, underline=u"", **styles):
            strings = [cypher_str(value).splitlines(False) for value in values]
            height = max(map(len, strings)) if strings else 1
            for y in range(height):
                line_text = u""
                underline_text = u""
                for x, _ in enumerate(values):
                    try:
                        text = strings[x][y]
                    except IndexError:
                        text = u""
                    if auto_align and self._fields[x]["numeric"]:
                        text = space + text.rjust(widths[x]) + space
                        u_text = underline * len(text)
                    else:
                        text = space + text.ljust(widths[x]) + space
                        u_text = underline * len(text)
                    if x > 0:
                        text = separator + text
                        u_text = separator + u_text
                    line_text += text
                    underline_text += u_text
                if underline:
                    line_text += newline + underline_text
                line_text += newline
                secho(line_text, file, nl=False, **styles)

        def apply(f):
            count = 0
            for count, index in enumerate(self._range(skip, limit), start=1):
                if count == 1 and header:
                    f(self.keys(), underline=u"-")
                f(self[index])
            return count

        apply(calc_widths)
        return apply(write_line)

    def write_html(self, file=None, header=None, skip=None, limit=None, auto_align=True):
        """ Write data to an HTML table.

        :param file:
        :param header:
        :param skip:
        :param limit:
        :param auto_align:
        :return:
        """
        from click import echo

        def write_tr(values, tag):
            echo(u"<tr>", file, nl=False)
            for i, value in enumerate(values):
                if auto_align and self._fields[i]["numeric"]:
                    template = u'<{} style="text-align:right">{}</{}>'
                else:
                    template = u'<{} style="text-align:left">{}</{}>'
                echo(template.format(tag, html_escape(cypher_str(value)), tag), file, nl=False)
            echo(u"</tr>", file, nl=False)

        count = 0
        echo(u"<table>", file, nl=False)
        for count, index in enumerate(self._range(skip, limit), start=1):
            if count == 1 and header:
                write_tr(self.keys(), u"th")
            write_tr(self[index], u"td")
        echo(u"</table>", file, nl=False)
        return count

    def write_separated_values(self, separator, file=None, header=None, skip=None, limit=None,
                               newline=u"\r\n", quote=u"\""):
        """ Write data to a delimiter-separated file.

        :param separator:
        :param file:
        :param header:
        :param skip:
        :param limit:
        :param newline:
        :param quote:
        :return:
        """
        from click import secho

        escaped_quote = quote + quote
        quotable = separator + newline + quote
        header_styles = {}
        if header and isinstance(header, dict):
            header_styles.update(header)

        def write_value(value, **styles):
            if value is None:
                return
            if isinstance(value, string_types):
                value = ustr(value)
                if any(ch in value for ch in quotable):
                    value = quote + value.replace(quote, escaped_quote) + quote
            else:
                value = cypher_repr(value)
            secho(value, file, nl=False, **styles)

        def write_line(values, **styles):
            for i, value in enumerate(values):
                if i > 0:
                    secho(separator, file, nl=False, **styles)
                write_value(value, **styles)
            secho(newline, file, nl=False, **styles)

        def apply(f):
            count = 0
            for count, index in enumerate(self._range(skip, limit), start=1):
                if count == 1 and header:
                    f(self.keys(), underline=u"-", **header_styles)
                f(self[index])
            return count

        return apply(write_line)

    def write_csv(self, file=None, header=None, skip=None, limit=None):
        """ Write the data as RFC4180-compatible comma-separated values.

        :param file
        :param header:
        :param skip:
        :param limit:
        :return:
        """
        return self.write_separated_values(u",", file, header, skip, limit)

    def write_tsv(self, file=None, header=None, skip=None, limit=None):
        """ Write the data as tab-separated values.

        :param file
        :param header:
        :param skip:
        :param limit:
        :return:
        """
        return self.write_separated_values(u"\t", file, header, skip, limit)
