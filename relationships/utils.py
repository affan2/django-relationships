from django.db.models import Q, QuerySet
from django.db import connections, router, transaction, signals

# from .models import RelationshipStatus
from .compat import User


def relationship_exists(from_user, to_user, status_slug='following'):
    status = RelationshipStatus.objects.by_slug(status_slug)
    if status.from_slug == status_slug:
        return from_user.relationships.exists(to_user, status)
    elif status.to_slug == status_slug:
        return to_user.relationships.exists(from_user, status)
    else:
        return from_user.relationships.exists(to_user, status, True)


def extract_user_field(model):
    for field in model._meta.fields + model._meta.many_to_many:
        if field.rel and field.rel.to == User:
            return field.name
    for rel in model._meta.get_all_related_many_to_many_objects():
        if rel.model == User:
            return rel.var_name


def positive_filter(qs, user_qs, user_lookup=None):
    if not user_lookup:
        user_lookup = extract_user_field(qs.model)

    if not user_lookup:
        return qs.none()  # default to returning none

    query = {'%s__in' % user_lookup: user_qs}

    return qs.filter(**query).distinct()


def negative_filter(qs, user_qs, user_lookup=None):
    if not user_lookup:
        user_lookup = extract_user_field(qs.model)

    if not user_lookup:
        return qs  # default to returning all

    query = {'%s__in' % user_lookup: user_qs}

    return qs.exclude(**query).distinct()


# Copied from django 1.8. Needed for the models.py module.
# Removed in Django 2.2, but no replacement was provided.
# django-relationships still needs its functionality however, especially for the models.py module.
def create_many_related_manager(superclass, rel):
    """Creates a manager that subclasses 'superclass' (which is a Manager)
    and adds behavior for many-to-many related objects."""
    class ManyRelatedManager(superclass):
        def __init__(self, model=None, query_field_name=None, instance=None, symmetrical=None,
                     source_field_name=None, target_field_name=None, reverse=False,
                     through=None, prefetch_cache_name=None):
            super(ManyRelatedManager, self).__init__()
            self.model = model
            self.query_field_name = query_field_name

            source_field = through._meta.get_field(source_field_name)
            source_related_fields = source_field.related_fields

            self.core_filters = {}
            for lh_field, rh_field in source_related_fields:
                self.core_filters['%s__%s' % (query_field_name, rh_field.name)] = getattr(instance, rh_field.attname)

            self.instance = instance
            self.symmetrical = symmetrical
            self.source_field = source_field
            self.target_field = through._meta.get_field(target_field_name)
            self.source_field_name = source_field_name
            self.target_field_name = target_field_name
            self.reverse = reverse
            self.through = through
            self.prefetch_cache_name = prefetch_cache_name
            self.related_val = source_field.get_foreign_related_value(instance)
            if None in self.related_val:
                raise ValueError('"%r" needs to have a value for field "%s" before '
                                 'this many-to-many relationship can be used.' %
                                 (instance, source_field_name))
            # Even if this relation is not to pk, we require still pk value.
            # The wish is that the instance has been already saved to DB,
            # although having a pk value isn't a guarantee of that.
            if instance.pk is None:
                raise ValueError("%r instance needs to have a primary key value before "
                                 "a many-to-many relationship can be used." %
                                 instance.__class__.__name__)

        def __call__(self, **kwargs):
            # We use **kwargs rather than a kwarg argument to enforce the
            # `manager='manager_name'` syntax.
            manager = getattr(self.model, kwargs.pop('manager'))
            manager_class = create_many_related_manager(manager.__class__, rel)
            return manager_class(
                model=self.model,
                query_field_name=self.query_field_name,
                instance=self.instance,
                symmetrical=self.symmetrical,
                source_field_name=self.source_field_name,
                target_field_name=self.target_field_name,
                reverse=self.reverse,
                through=self.through,
                prefetch_cache_name=self.prefetch_cache_name,
            )
        do_not_call_in_templates = True

        def _build_remove_filters(self, removed_vals):
            filters = Q(**{self.source_field_name: self.related_val})
            # No need to add a subquery condition if removed_vals is a QuerySet without
            # filters.
            removed_vals_filters = (not isinstance(removed_vals, QuerySet) or
                                    removed_vals._has_filters())
            if removed_vals_filters:
                filters &= Q(**{'%s__in' % self.target_field_name: removed_vals})
            if self.symmetrical:
                symmetrical_filters = Q(**{self.target_field_name: self.related_val})
                if removed_vals_filters:
                    symmetrical_filters &= Q(
                        **{'%s__in' % self.source_field_name: removed_vals})
                filters |= symmetrical_filters
            return filters

        def get_queryset(self):
            try:
                return self.instance._prefetched_objects_cache[self.prefetch_cache_name]
            except (AttributeError, KeyError):
                qs = super(ManyRelatedManager, self).get_queryset()
                qs._add_hints(instance=self.instance)
                if self._db:
                    qs = qs.using(self._db)
                return qs._next_is_sticky().filter(**self.core_filters)

        def get_prefetch_queryset(self, instances, queryset=None):
            if queryset is None:
                queryset = super(ManyRelatedManager, self).get_queryset()

            queryset._add_hints(instance=instances[0])
            queryset = queryset.using(queryset._db or self._db)

            query = {'%s__in' % self.query_field_name: instances}
            queryset = queryset._next_is_sticky().filter(**query)

            # M2M: need to annotate the query in order to get the primary model
            # that the secondary model was actually related to. We know that
            # there will already be a join on the join table, so we can just add
            # the select.

            # For non-autocreated 'through' models, can't assume we are
            # dealing with PK values.
            fk = self.through._meta.get_field(self.source_field_name)
            join_table = self.through._meta.db_table
            connection = connections[queryset.db]
            qn = connection.ops.quote_name
            queryset = queryset.extra(select={
                '_prefetch_related_val_%s' % f.attname:
                    '%s.%s' % (qn(join_table), qn(f.column)) for f in fk.local_related_fields})
            return (
                queryset,
                lambda result: tuple(
                    getattr(result, '_prefetch_related_val_%s' % f.attname)
                    for f in fk.local_related_fields
                ),
                lambda inst: tuple(
                    f.get_db_prep_value(getattr(inst, f.attname), connection)
                    for f in fk.foreign_related_fields
                ),
                False,
                self.prefetch_cache_name,
            )

        def add(self, *objs):
            if not rel.through._meta.auto_created:
                opts = self.through._meta
                raise AttributeError(
                    "Cannot use add() on a ManyToManyField which specifies an "
                    "intermediary model. Use %s.%s's Manager instead." %
                    (opts.app_label, opts.object_name)
                )

            db = router.db_for_write(self.through, instance=self.instance)
            with transaction.atomic(using=db, savepoint=False):
                self._add_items(self.source_field_name, self.target_field_name, *objs)

                # If this is a symmetrical m2m relation to self, add the mirror entry in the m2m table
                if self.symmetrical:
                    self._add_items(self.target_field_name, self.source_field_name, *objs)
        add.alters_data = True

        def remove(self, *objs):
            if not rel.through._meta.auto_created:
                opts = self.through._meta
                raise AttributeError(
                    "Cannot use remove() on a ManyToManyField which specifies "
                    "an intermediary model. Use %s.%s's Manager instead." %
                    (opts.app_label, opts.object_name)
                )
            self._remove_items(self.source_field_name, self.target_field_name, *objs)
        remove.alters_data = True

        def clear(self):
            db = router.db_for_write(self.through, instance=self.instance)
            with transaction.atomic(using=db, savepoint=False):
                signals.m2m_changed.send(sender=self.through, action="pre_clear",
                                         instance=self.instance, reverse=self.reverse,
                                         model=self.model, pk_set=None, using=db)

                filters = self._build_remove_filters(super(ManyRelatedManager, self).get_queryset().using(db))
                self.through._default_manager.using(db).filter(filters).delete()

                signals.m2m_changed.send(sender=self.through, action="post_clear",
                                         instance=self.instance, reverse=self.reverse,
                                         model=self.model, pk_set=None, using=db)
        clear.alters_data = True

        def create(self, **kwargs):
            # This check needs to be done here, since we can't later remove this
            # from the method lookup table, as we do with add and remove.
            if not self.through._meta.auto_created:
                opts = self.through._meta
                raise AttributeError(
                    "Cannot use create() on a ManyToManyField which specifies "
                    "an intermediary model. Use %s.%s's Manager instead." %
                    (opts.app_label, opts.object_name)
                )
            db = router.db_for_write(self.instance.__class__, instance=self.instance)
            new_obj = super(ManyRelatedManager, self.db_manager(db)).create(**kwargs)
            self.add(new_obj)
            return new_obj
        create.alters_data = True

        def get_or_create(self, **kwargs):
            db = router.db_for_write(self.instance.__class__, instance=self.instance)
            obj, created = super(ManyRelatedManager, self.db_manager(db)).get_or_create(**kwargs)
            # We only need to add() if created because if we got an object back
            # from get() then the relationship already exists.
            if created:
                self.add(obj)
            return obj, created
        get_or_create.alters_data = True

        def update_or_create(self, **kwargs):
            db = router.db_for_write(self.instance.__class__, instance=self.instance)
            obj, created = super(ManyRelatedManager, self.db_manager(db)).update_or_create(**kwargs)
            # We only need to add() if created because if we got an object back
            # from get() then the relationship already exists.
            if created:
                self.add(obj)
            return obj, created
        update_or_create.alters_data = True

        def _add_items(self, source_field_name, target_field_name, *objs):
            # source_field_name: the PK fieldname in join table for the source object
            # target_field_name: the PK fieldname in join table for the target object
            # *objs - objects to add. Either object instances, or primary keys of object instances.

            # If there aren't any objects, there is nothing to do.
            from django.db.models import Model
            if objs:
                new_ids = set()
                for obj in objs:
                    if isinstance(obj, self.model):
                        if not router.allow_relation(obj, self.instance):
                            raise ValueError(
                                'Cannot add "%r": instance is on database "%s", value is on database "%s"' %
                                (obj, self.instance._state.db, obj._state.db)
                            )
                        fk_val = self.through._meta.get_field(
                            target_field_name).get_foreign_related_value(obj)[0]
                        if fk_val is None:
                            raise ValueError(
                                'Cannot add "%r": the value for field "%s" is None' %
                                (obj, target_field_name)
                            )
                        new_ids.add(fk_val)
                    elif isinstance(obj, Model):
                        raise TypeError(
                            "'%s' instance expected, got %r" %
                            (self.model._meta.object_name, obj)
                        )
                    else:
                        new_ids.add(obj)

                db = router.db_for_write(self.through, instance=self.instance)
                vals = (self.through._default_manager.using(db)
                        .values_list(target_field_name, flat=True)
                        .filter(**{
                    source_field_name: self.related_val[0],
                    '%s__in' % target_field_name: new_ids,
                }))
                new_ids = new_ids - set(vals)

                with transaction.atomic(using=db, savepoint=False):
                    if self.reverse or source_field_name == self.source_field_name:
                        # Don't send the signal when we are inserting the
                        # duplicate data row for symmetrical reverse entries.
                        signals.m2m_changed.send(sender=self.through, action='pre_add',
                                                 instance=self.instance, reverse=self.reverse,
                                                 model=self.model, pk_set=new_ids, using=db)

                    # Add the ones that aren't there already
                    self.through._default_manager.using(db).bulk_create([
                        self.through(**{
                            '%s_id' % source_field_name: self.related_val[0],
                            '%s_id' % target_field_name: obj_id,
                        })
                        for obj_id in new_ids
                    ])

                    if self.reverse or source_field_name == self.source_field_name:
                        # Don't send the signal when we are inserting the
                        # duplicate data row for symmetrical reverse entries.
                        signals.m2m_changed.send(sender=self.through, action='post_add',
                                                 instance=self.instance, reverse=self.reverse,
                                                 model=self.model, pk_set=new_ids, using=db)

        def _remove_items(self, source_field_name, target_field_name, *objs):
            # source_field_name: the PK colname in join table for the source object
            # target_field_name: the PK colname in join table for the target object
            # *objs - objects to remove
            if not objs:
                return

            # Check that all the objects are of the right type
            old_ids = set()
            for obj in objs:
                if isinstance(obj, self.model):
                    fk_val = self.target_field.get_foreign_related_value(obj)[0]
                    old_ids.add(fk_val)
                else:
                    old_ids.add(obj)

            db = router.db_for_write(self.through, instance=self.instance)
            with transaction.atomic(using=db, savepoint=False):
                # Send a signal to the other end if need be.
                signals.m2m_changed.send(sender=self.through, action="pre_remove",
                                         instance=self.instance, reverse=self.reverse,
                                         model=self.model, pk_set=old_ids, using=db)
                target_model_qs = super(ManyRelatedManager, self).get_queryset()
                if target_model_qs._has_filters():
                    old_vals = target_model_qs.using(db).filter(**{
                        '%s__in' % self.target_field.related_field.attname: old_ids})
                else:
                    old_vals = old_ids
                filters = self._build_remove_filters(old_vals)
                self.through._default_manager.using(db).filter(filters).delete()

                signals.m2m_changed.send(sender=self.through, action="post_remove",
                                         instance=self.instance, reverse=self.reverse,
                                         model=self.model, pk_set=old_ids, using=db)

    return ManyRelatedManager
