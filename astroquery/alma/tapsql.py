"""
Utilities for generating ADQL for ALMA TAP service
"""
from datetime import datetime

from astropy import units as u
import astropy.coordinates as coord
from astropy.time import Time

ALMA_DATE_FORMAT = '%d-%m-%Y'


def _gen_pos_sql(field, value):
    result = ''
    if field == 'SkyCoord.from_name':
        # resolve the source first
        if value:
            obj_coord = coord.SkyCoord.from_name(value)
            frame = 'icrs'
            ras = [str(obj_coord.icrs.ra.to(u.deg).value)]
            decs = [str(obj_coord.icrs.dec.to(u.deg).value)]
            radius = 10 * u.arcmin
        else:
            raise ValueError('Object name missing')
    else:
        if field == 's_ra, s_dec':
            frame = 'icrs'
        else:
            frame = 'galactic'
        radius = 10*u.arcmin
        if ',' in value:
            center_coord, rad = value.split(',')
            try:
                radius = float(rad.strip())*u.degree
            except ValueError:
                raise ValueError('Cannot parse radius in ' + value)
        else:
            center_coord = value.strip()
        try:
            ra, dec = center_coord.split(' ')
        except ValueError:
            raise ValueError('Cannot find ra/dec in ' + value)
        ras = _val_parse(ra, val_type=str)
        decs = _val_parse(dec, val_type=str)

    for ra in ras:
        for dec in decs:
            if result:
                result += ' OR '
            if isinstance(ra, str) and isinstance(dec, str):
                # circle
                center = coord.SkyCoord(ra, dec,
                                        unit=(u.deg, u.deg),
                                        frame=frame)
                result += \
                    "(INTERSECTS(CIRCLE('ICRS',{},{},{}), s_region) = 1)".\
                    format(center.icrs.ra.to(u.deg).value,
                           center.icrs.dec.to(u.deg).value,
                           radius.to(u.deg).value)
            elif isinstance(ra, tuple) and isinstance(dec, tuple):
                # range
                ra_min, ra_max = ra
                if ra_min is None:
                    ra_min = 0
                if ra_max is None:
                    ra_max = 360
                dec_min, dec_max = dec
                if dec_min is None:
                    dec_min = -90
                if dec_max is None:
                    dec_max = 90
                ra_min = coord.Angle(ra_min, unit=u.degree).deg
                ra_max = coord.Angle(ra_max, unit=u.degree).deg
                dec_min = coord.Angle(dec_min, unit=u.degree).deg
                dec_max = coord.Angle(dec_max, unit=u.degree).deg
                if frame == 'galactic':
                    # intersect with s_region is too complicated. ALMA indicated that
                    # the use of gal_longitude and gal_latitude is good enough
                    # approximation in this less common use case
                    result += ('gal_longitude>={} AND gal_longitude<={} AND '
                               'gal_latitude>={} AND gal_latitude<={}').format(
                        ra_min, ra_max, dec_min, dec_max)
                else:
                    result += \
                        "(INTERSECTS(RANGE_S2D({},{},{},{}), s_region) = 1)".\
                        format(ra_min, ra_max, dec_min, dec_max)
            else:
                raise ValueError('Cannot interpret ra({}), dec({}'.
                                 format(ra, dec))
    if ' OR ' in result:
        # use brackets for multiple ORs
        return '(' + result + ')'
    else:
        return result


def _gen_numeric_sql(field, value):
    result = ''
    for interval in _val_parse(value, float):
        if result:
            result += ' OR '
        if isinstance(interval, tuple):
            int_min, int_max = interval
            if int_min is None:
                if int_max is None:
                    # no constraints on bandwith
                    pass
                else:
                    result += '{}<={}'.format(field, int_max)
            elif int_max is None:
                result += '{}>={}'.format(field, int_min)
            else:
                result += '({1}<={0} AND {0}<={2})'.format(field, int_min,
                                                           int_max)
        else:
            result += '{}={}'.format(field, interval)
    if ' OR ' in result:
        # use brakets for multiple ORs
        return '(' + result + ')'
    else:
        return result


def _gen_str_sql(field, value):
    result = ''
    for interval in _val_parse(value, str):
        if result:
            result += ' OR '
        if '*' in interval:
            # use LIKE
            # escape wildcards if they exists in the value
            interval = interval.replace('%', r'\%')  # noqa
            interval = interval.replace('_', r'\_')  # noqa
            # ADQL wild cards are % and _
            interval = interval.replace('*', '%')
            interval = interval.replace('?', '_')
            result += "{} LIKE '{}'".format(field, interval)
        else:
            result += "{}='{}'".format(field, interval)
    if ' OR ' in result:
        # use brackets for multiple ORs
        return '(' + result + ')'
    else:
        return result


def _gen_datetime_sql(field, value):
    result = ''
    for interval in _val_parse(value, str):
        if result:
            result += ' OR '
        if isinstance(interval, tuple):
            min_datetime, max_datetime = interval
            if max_datetime is None:
                result += "{}>={}".format(
                    field, Time(datetime.strptime(min_datetime, ALMA_DATE_FORMAT)).mjd)
            elif min_datetime is None:
                result += "{}<={}".format(
                    field, Time(datetime.strptime(max_datetime, ALMA_DATE_FORMAT)).mjd)
            else:
                result += "({1}<={0} AND {0}<={2})".format(
                    field, Time(datetime.strptime(min_datetime, ALMA_DATE_FORMAT)).mjd,
                    Time(datetime.strptime(max_datetime, ALMA_DATE_FORMAT)).mjd)
        else:
            # TODO is it just a value (midnight) or the entire day?
            result += "{}={}".format(
                field, Time(datetime.strptime(interval, ALMA_DATE_FORMAT)).mjd)
    if ' OR ' in result:
        # use brackets for multiple ORs
        return '(' + result + ')'
    else:
        return result


def _gen_pub_sql(field, value):
    if value is True:
        return "{}='Public'".format(field)
    elif value is False:
        return "{}='Proprietary'".format(field)
    else:
        return None


def _gen_science_sql(field, value):
    if value is True:
        return "{}='T'".format(field)
    elif value is False:
        return "{}='F'".format(field)
    else:
        return None


def _gen_band_list_sql(field, value):
    # band list value is expected to be space separated list of bands
    if isinstance(value, list):
        val = value
    else:
        val = value.split(' ')
    return _gen_str_sql(field, '|'.join(
        ['*{}*'.format(_) for _ in val]))


def _gen_pol_sql(field, value):
    # band list value is expected to be space separated list of bands
    val = ''
    states_map = {'Stokes I': '*I*',
                  'Single': '/XX/',
                  'Dual': '/XX/YY/',
                  'Full': '/XX/XY/YX/YY/'}
    for state in states_map:
        if state in value:
            if val:
                val += '|'
            val += states_map[state]
    return _gen_str_sql(field, val)


def _val_parse(value, val_type=float):
    # parses an ALMA query field and returns a list of values (of type
    # val_type) or tuples representing parsed values or intervals. Open
    # intervals have None at one of the ends
    def _one_val_parse(value, val_type=float):
        # parses the value and returns corresponding interval for
        # sia to work with. E.g <2 => (None, 2)
        if value.startswith('<'):
            return (None, val_type(value[1:]))
        elif value.startswith('>'):
            return (val_type(value[1:]), None)
        else:
            return val_type(value)
    result = []
    if isinstance(value, str):
        try:
            if value.startswith('!'):
                start, end = _val_parse(value[2:-1].strip(), val_type=val_type)[0]
                result.append((None, start))
                result.append((end, None))
            elif value.startswith('('):
                result += _val_parse(value[1:-1], val_type=val_type)
            elif '|' in value:
                for vv in value.split('|'):
                    result += _val_parse(vv.strip(), val_type=val_type)
            elif '..' in value:
                start, end = value.split('..')
                if not start or not end:
                    raise ValueError('start or end interval missing in {}'.
                                     format(value))
                result.append((_one_val_parse(start.strip(), val_type=val_type),
                               _one_val_parse(end.strip(), val_type=val_type)))
            else:
                result.append(_one_val_parse(value, val_type=val_type))
        except Exception as e:
            raise ValueError(
                'Error parsing {}. Details: {}'.format(value, str(e)))
    elif isinstance(value, list):
        result = value
    else:
        result.append(value)
    return result
