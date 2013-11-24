from django import template
from django.core.urlresolvers import reverse
from django.db.models.loading import get_model
from django.template import TemplateSyntaxError, Node, Variable
from django.utils.functional import wraps
from relationships.models import RelationshipStatus
from relationships.utils import positive_filter, negative_filter, relationship_exists
from django.contrib.contenttypes.models import ContentType
from social_friends_finder.models import SocialFriendList
from django.core.cache import cache
from django.template import loader, RequestContext

register = template.Library()


class IfRelationshipNode(template.Node):
    def __init__(self, nodelist_true, nodelist_false, *args):
        self.nodelist_true = nodelist_true
        self.nodelist_false = nodelist_false
        self.from_user, self.to_user, self.status = args
        self.status = self.status.replace('"', '')  # strip quotes

    def render(self, context):
        from_user = template.resolve_variable(self.from_user, context)
        to_user = template.resolve_variable(self.to_user, context)

        if from_user.is_anonymous() or to_user.is_anonymous():
            return self.nodelist_false.render(context)

        try:
            status = RelationshipStatus.objects.by_slug(self.status)
        except RelationshipStatus.DoesNotExist:
            raise template.TemplateSyntaxError('RelationshipStatus not found')

        if status.from_slug == self.status:
            val = from_user.relationships.exists(to_user, status)
        elif status.to_slug == self.status:
            val = to_user.relationships.exists(from_user, status)
        else:
            val = from_user.relationships.exists(to_user, status, symmetrical=True)

        if val:
            return self.nodelist_true.render(context)

        return self.nodelist_false.render(context)


@register.tag
def if_relationship(parser, token):
    """
    Determine if a certain type of relationship exists between two users.
    The ``status`` parameter must be a slug matching either the from_slug,
    to_slug or symmetrical_slug of a RelationshipStatus.

    Example::

        {% if_relationship from_user to_user "friends" %}
            Here are pictures of me drinking alcohol
        {% else %}
            Sorry coworkers
        {% endif_relationship %}

        {% if_relationship from_user to_user "blocking" %}
            damn seo experts
        {% endif_relationship %}
    """
    bits = list(token.split_contents())
    if len(bits) != 4:
        raise TemplateSyntaxError, "%r takes 3 arguments:\n%s" % \
            (bits[0], if_relationship.__doc__)
    end_tag = 'end' + bits[0]
    nodelist_true = parser.parse(('else', end_tag))
    token = parser.next_token()
    if token.contents == 'else':
        nodelist_false = parser.parse((end_tag,))
        parser.delete_first_token()
    else:
        nodelist_false = template.NodeList()
    return IfRelationshipNode(nodelist_true, nodelist_false, *bits[1:])


@register.filter
def add_relationship_url(user, status):
    """
    Generate a url for adding a relationship on a given user.  ``user`` is a
    User object, and ``status`` is either a relationship_status object or a
    string denoting a RelationshipStatus

    Usage::

        href="{{ user|add_relationship_url:"following" }}"
    """
    if isinstance(status, RelationshipStatus):
        status = status.from_slug
    return reverse('relationship_add', args=[user.username, status])


@register.filter
def remove_relationship_url(user, status):
    """
    Generate a url for removing a relationship on a given user.  ``user`` is a
    User object, and ``status`` is either a relationship_status object or a
    string denoting a RelationshipStatus

    Usage::

        href="{{ user|remove_relationship_url:"following" }}"
    """
    if isinstance(status, RelationshipStatus):
        status = status.from_slug
    return reverse('relationship_remove', args=[user.username, status])


def positive_filter_decorator(func):
    def inner(qs, user):
        if isinstance(qs, basestring):
            model = get_model(*qs.split('.'))
            if not model:
                return []
            qs = model._default_manager.all()
        if user.is_anonymous():
            return qs.none()
        return func(qs, user)
    inner._decorated_function = getattr(func, '_decorated_function', func)
    return wraps(func)(inner)


def negative_filter_decorator(func):
    def inner(qs, user):
        if isinstance(qs, basestring):
            model = get_model(*qs.split('.'))
            if not model:
                return []
            qs = model._default_manager.all()
        if user.is_anonymous():
            return qs
        return func(qs, user)
    inner._decorated_function = getattr(func, '_decorated_function', func)
    return wraps(func)(inner)


@register.filter
@positive_filter_decorator
def friend_content(qs, user):
    return positive_filter(qs, user.relationships.friends())


@register.filter
@positive_filter_decorator
def following_content(qs, user):
    return positive_filter(qs, user.relationships.following())


@register.filter
@positive_filter_decorator
def followers_content(qs, user):
    return positive_filter(qs, user.relationships.followers())


@register.filter
@negative_filter_decorator
def unblocked_content(qs, user):
    return negative_filter(qs, user.relationships.blocking())

class FollowerList(Node):
    def __init__(self, user):
        self.user = Variable(user)

    def render(self, context):
        user_instance = self.user.resolve(context)
        content_type = ContentType.objects.get_for_model(user_instance).pk
        return reverse('get_followers', kwargs={'content_type_id': content_type, 'object_id': user_instance.pk })
@register.tag
def follower_info_url(parser, token):
    bits = token.split_contents()
    if len(bits) != 2:
        raise TemplateSyntaxError("Accepted format {% follower_info_url [instance] %}")
    else:
        return FollowerList(bits[1])

class FollowingList(Node):
    def __init__(self, user):
        self.user = Variable(user)

    def render(self, context):
        user_instance = self.user.resolve(context)
        content_type = ContentType.objects.get_for_model(user_instance).pk
        return reverse('get_following', kwargs={'content_type_id': content_type, 'object_id': user_instance.pk })
        
@register.tag
def following_info_url(parser, token):
    bits = token.split_contents()
    if len(bits) != 2:
        raise TemplateSyntaxError("Accepted format {% following_info_url [instance] %}")
    else:
        return FollowingList(bits[1])

class AsNode(template.Node):
    """
    Base template Node class for template tags that takes a predefined number
    of arguments, ending in an optional 'as var' section.
    """
    args_count = 3

    @classmethod
    def handle_token(cls, parser, token):
        """
        Class method to parse and return a Node.
        """
        bits = token.split_contents()
        args_count = len(bits) - 1
        if args_count >= 2 and bits[-2] == 'as':
            as_var = bits[-1]
            args_count -= 2
        else:
            as_var = None
        if args_count != cls.args_count:
            arg_list = ' '.join(['[arg]' * cls.args_count])
            raise template.TemplateSyntaxError("Accepted formats {%% %(tagname)s "
                "%(args)s %%} or {%% %(tagname)s %(args)s as [var] %%}" %
                {'tagname': bits[0], 'args': arg_list})
        args = [parser.compile_filter(token) for token in
            bits[1:args_count + 1]]
        return cls(args, varname=as_var)

    def __init__(self, args, varname=None):
        self.args = args
        self.varname = varname

    def render(self, context):
        result = self.render_result(context)
        if self.varname is not None:
            context[self.varname] = result
            return ''
        return result

    def render_result(self, context):
        raise NotImplementedError("Must be implemented by a subclass")

class FollowingListSubset(AsNode):

    def render_result(self, context):
        obj_instance = self.args[0].resolve(context)
        sIndex = self.args[1].resolve(context)
        lIndex = self.args[2].resolve(context)
        content_type = ContentType.objects.get_for_model(obj_instance).pk
        
        return reverse('get_following_subset', kwargs={
            'content_type_id': content_type, 'object_id': obj_instance.pk, 'sIndex':sIndex, 'lIndex':lIndex})

@register.tag
def following_subset_url(parser, token):
    bits = token.split_contents()
    if len(bits) != 6:
        raise template.TemplateSyntaxError("Accepted format "
                                  "{% following_subset_url [actor_instance] %}")
    else:
        return FollowingListSubset.handle_token(parser, token)

class FollowerListSubset(AsNode):

    def render_result(self, context):
        obj_instance = self.args[0].resolve(context)
        sIndex = self.args[1].resolve(context)
        lIndex = self.args[2].resolve(context)
        content_type = ContentType.objects.get_for_model(obj_instance).pk
        
        return reverse('get_follower_subset', kwargs={
            'content_type_id': content_type, 'object_id': obj_instance.pk, 'sIndex':sIndex, 'lIndex':lIndex})

@register.tag
def follower_subset_url(parser, token):
    bits = token.split_contents()
    if len(bits) != 6:
        raise template.TemplateSyntaxError("Accepted format "
                                  "{% follower_subset_url [actor_instance] %}")
    else:
        return FollowerListSubset.handle_token(parser, token)

class GetRelationshipType(Node):
    def __init__(self, user1, user2, context_var):
        self.user1 = user1
        self.user2 = user2
        self.context_var = context_var

    def render(self, context):
        user1_instance = template.resolve_variable(self.user1, context)
        user2_instance = template.resolve_variable(self.user2, context)
        if user2_instance == user1_instance:
            context[self.context_var] = 'self'
            return ''

        social_auth_backend = None

        user_social_auth = user1_instance.social_auth.filter(provider="facebook")
        if user_social_auth.exists():
            social_auth_backend = "facebook"
        else:
            user_social_auth = user1_instance.social_auth.filter(provider="twitter")
            if user_social_auth.exists():
                social_auth_backend = "twitter"

        if user_social_auth.exists():
            friends = cache.get(user1_instance.username+"SocialFriendList")
            if friends is None:
                friends = SocialFriendList.objects.existing_social_friends(user_social_auth[0])
                cache.set(user1_instance.username+"SocialFriendList", friends)

            if user2_instance in friends and relationship_exists(user1_instance, user2_instance, 'following'):
                context[self.context_var] = social_auth_backend
                return ''

        if relationship_exists(user1_instance, user2_instance, 'following'):
            context[self.context_var] = 'level1'
            return ''
        else:
            friends = user1_instance.relationships.following()
            for friend in friends:
                if user2_instance in friend.relationships.following() and user2_instance != user1_instance:
                    context[self.context_var] = 'level2'
                    return ''

        context[self.context_var] = ''
        return ''        
        

@register.tag
def get_relationship_type(parser, token):
    bits = token.split_contents()
    if len(bits) != 5:
        raise TemplateSyntaxError("Accepted format "
                                  "{% get_relationship_type [user_instance] [user_instance] as rel_type %}")
    elif bits[3] != 'as':
        raise template.TemplateSyntaxError("Third argument to '%s' tag must be 'as'" % bits[0])
    else:
        return GetRelationshipType(bits[1], bits[2], bits[4])

@register.simple_tag(takes_context=True)
def render_follower_subset(context, user_obj, sIndex, lIndex, data_chunk):
    template_name = "relationships/friend_list_all.html"
    template = loader.get_template(template_name)
    content_type = ContentType.objects.get_for_model(user_obj).pk
    data_href = reverse('get_follower_subset', kwargs={
            'content_type_id': content_type, 'object_id': user_obj.pk, 'sIndex':sIndex, 'lIndex':lIndex})
    return template.render(RequestContext(context['request'], {
            "profile_user": user_obj,
            "friends": user_obj.relationships.followers()[sIndex:lIndex],
            'is_incremental': False,
            'data_href': data_href,
            'data_chunk': data_chunk
        }))

@register.simple_tag(takes_context=True)
def render_following_subset(context, user_obj, sIndex, lIndex, data_chunk):
    template_name = "relationships/friend_list_all.html"
    template = loader.get_template(template_name)
    content_type = ContentType.objects.get_for_model(user_obj).pk
    data_href = reverse('get_following_subset', kwargs={
            'content_type_id': content_type, 'object_id': user_obj.pk, 'sIndex':sIndex, 'lIndex':lIndex})
    return template.render(RequestContext(context['request'], {
            "profile_user": user_obj,
            "friends": user_obj.relationships.following()[sIndex:lIndex],
            'is_incremental': False,
            'data_href':data_href,
            'data_chunk': data_chunk
        }))